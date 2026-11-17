# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Preview and apply a Microsoft Project XML (MSPDI) file.

Two steps, the same file read twice by :func:`parse_mspdi`:

* ``preview`` changes nothing. It returns the tasks as they will land, the
  counts, and the ``schedule_mspdi_import`` validation report. ``can_apply`` is
  false while any ERROR is open (a task without dates, a duplicate UID).
* ``apply`` refuses a file with errors, then creates the activities with their
  parents, the links, the calendars (as project calendars in the advanced
  scheduling module, reused when one of the same name and week exists), and,
  when the file carries baseline 0, one unapproved programme baseline so the
  planner decides whether it becomes the approved one.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.validation.engine import validation_engine
from app.modules.schedule.baseline_revisions import next_baseline_label
from app.modules.schedule.constraints import normalize_constraint
from app.modules.schedule.import_source import ImportSourceService
from app.modules.schedule.mspdi_import import MspdiDocument, MspdiReadError, parse_mspdi
from app.modules.schedule.validators import MSPDI_IMPORT_RULE_SET

#: Rows of the preview table; the counts always cover the whole file.
PREVIEW_ROWS = 500


def read_or_400(raw: bytes) -> MspdiDocument:
    """Parse the file or answer 400 with the reason."""
    try:
        return parse_mspdi(raw)
    except MspdiReadError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


async def validation_issues(doc: MspdiDocument, *, schedule_id: uuid.UUID, locale: str | None) -> list[dict[str, Any]]:
    """Run the ``schedule_mspdi_import`` rules and return the failing results."""
    report = await validation_engine.validate(
        data=doc.validation_payload(),
        rule_sets=[MSPDI_IMPORT_RULE_SET],
        target_type="schedule_mspdi_import",
        target_id=str(schedule_id),
        metadata={"locale": locale} if locale else None,
    )
    out: list[dict[str, Any]] = []
    for result in report.results:
        if result.passed or result.is_engine_error:
            continue
        severity = result.severity.value if hasattr(result.severity, "value") else str(result.severity)
        out.append(
            {
                "rule_id": result.rule_id,
                "code": str(result.details.get("code") or "fail"),
                "severity": str(severity),
                "ref": result.element_ref or "",
                "message": result.message,
            }
        )
    return out


def preview_document(doc: MspdiDocument, issues: list[dict[str, Any]]) -> dict[str, Any]:
    """The preview payload: counts, date span, the report and the first task rows."""
    preds: dict[str, int] = {}
    for link in doc.links:
        preds[link.successor_uid] = preds.get(link.successor_uid, 0) + 1
    starts = [t.start for t in doc.tasks if t.start]
    finishes = [t.finish for t in doc.tasks if t.finish]
    errors = sum(1 for i in issues if i["severity"] == "error")
    return {
        "name": doc.name,
        "minutes_per_day": doc.minutes_per_day,
        "task_count": len(doc.tasks),
        "summary_count": sum(1 for t in doc.tasks if t.activity_type == "summary"),
        "milestone_count": sum(1 for t in doc.tasks if t.activity_type == "milestone"),
        "link_count": len(doc.links),
        "calendar_count": len(doc.calendars),
        "baseline_task_count": sum(1 for t in doc.tasks if t.baseline_start and t.baseline_finish),
        "start": min(starts) if starts else None,
        "finish": max(finishes) if finishes else None,
        "error_count": errors,
        "warning_count": sum(1 for i in issues if i["severity"] != "error"),
        "can_apply": errors == 0,
        "issues": issues,
        "calendars": [
            {"uid": c.uid, "name": c.name, "work_days": c.work_days, "holiday_count": len(c.holidays)}
            for c in doc.calendars
        ],
        "tasks": [
            {
                "uid": t.uid,
                "name": t.name,
                "wbs": t.wbs,
                "outline_level": t.outline_level,
                "parent_uid": t.parent_uid,
                "start": t.start or None,
                "finish": t.finish or None,
                "duration_days": t.duration_days,
                "percent_complete": t.percent_complete,
                "activity_type": t.activity_type,
                "baseline_start": t.baseline_start,
                "baseline_finish": t.baseline_finish,
                "predecessor_count": preds.get(t.uid, 0),
            }
            for t in doc.tasks[:PREVIEW_ROWS]
        ],
    }


class MspdiImportService:
    """Write a checked MSPDI document into an existing schedule."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _calendars(self, project_id: uuid.UUID, doc: MspdiDocument) -> dict[str, uuid.UUID]:
        from app.modules.schedule_advanced.models import Calendar

        if not doc.calendars:
            return {}
        rows = await self.session.execute(select(Calendar).where(Calendar.project_id == project_id))
        existing = list(rows.scalars().all())
        out: dict[str, uuid.UUID] = {}
        for cal in doc.calendars:
            match = next(
                (c for c in existing if c.name == cal.name and sorted(c.work_days or []) == cal.work_days),
                None,
            )
            if match is None:
                match = Calendar(
                    project_id=project_id,
                    name=cal.name[:255],
                    work_days=list(cal.work_days),
                    work_hours_per_day=Decimal(str(cal.hours_per_day)),
                    holidays=list(cal.holidays),
                    special_shifts={},
                    is_default=False,
                )
                self.session.add(match)
                await self.session.flush()
                existing.append(match)
            out[cal.uid] = match.id
        return out

    async def apply(
        self,
        schedule: Any,
        raw: bytes,
        *,
        filename: str,
        user_id: str,
        region: str | None,
        locale: str | None,
        max_seq: int,
    ) -> dict[str, Any]:
        """Create activities, links, calendars and the imported baseline. 422 while errors are open."""
        from app.modules.schedule.models import Activity, ScheduleRelationship
        from app.modules.schedule.service import compute_duration

        doc = read_or_400(raw)
        issues = await validation_issues(doc, schedule_id=schedule.id, locale=locale)
        errors = [i for i in issues if i["severity"] == "error"]
        if errors:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=f"The file has {len(errors)} error(s); check it and fix the source first. "
                + "; ".join(i["message"] for i in errors[:5]),
            )

        calendar_ids = await self._calendars(schedule.project_id, doc)
        project_calendar = calendar_ids.get(doc.project_calendar_uid or "")
        by_uid: dict[str, Activity] = {}
        for idx, task in enumerate(doc.tasks):
            duration = task.duration_days
            if duration is None:
                duration = max(0, compute_duration(task.start, task.finish, region))
            pct = task.percent_complete
            meta: dict[str, Any] = {
                "source": "msp_xml_import",
                "msp_uid": task.uid,
                "outline_level": str(task.outline_level),
            }
            if task.baseline_start and task.baseline_finish:
                meta["msp_baseline"] = {
                    "start": task.baseline_start,
                    "finish": task.baseline_finish,
                    "duration_days": task.baseline_duration_days,
                }
            parent = by_uid.get(task.parent_uid or "")
            activity = Activity(
                schedule_id=schedule.id,
                parent_id=parent.id if parent is not None else None,
                name=task.name[:255],
                description=task.name,
                wbs_code=task.wbs[:50],
                start_date=task.start,
                end_date=task.finish,
                duration_days=duration,
                progress_pct=str(pct),
                status="completed" if pct >= 100 else ("in_progress" if pct > 0 else "not_started"),
                activity_type=task.activity_type,
                dependencies=[],
                resources=[],
                boq_position_ids=[],
                color="#dc2626" if task.activity_type == "milestone" else "#0071e3",
                sort_order=idx + 1,
                activity_code=f"ACT-{max_seq + idx + 1:03d}",
                constraint_type=normalize_constraint(task.constraint_type),
                constraint_date=task.constraint_date,
                calendar_id=calendar_ids.get(task.calendar_uid or "") or project_calendar,
                metadata_=meta,
            )
            self.session.add(activity)
            await self.session.flush()
            by_uid[task.uid] = activity

        rels: list[Any] = []
        for link in doc.links:
            rel = ScheduleRelationship(
                schedule_id=schedule.id,
                predecessor_id=by_uid[link.predecessor_uid].id,
                successor_id=by_uid[link.successor_uid].id,
                relationship_type=link.relationship_type,
                lag_days=link.lag_days,
            )
            self.session.add(rel)
            rels.append(rel)
        await self.session.flush()

        baseline_id = await self._baseline(schedule, doc, by_uid, rels, user_id, filename)

        created = [a.id for a in by_uid.values()]
        source = await ImportSourceService(self.session).record_import(
            schedule.id, raw=raw, filename=filename, fmt="msp_xml", user_id=user_id, activity_ids=created
        )
        return {
            "activities_imported": len(created),
            "relationships_imported": len(rels),
            "calendars_imported": len(calendar_ids),
            "warnings": [i["message"] for i in issues],
            "source_document_id": source["document_id"],
            "baseline_id": str(baseline_id) if baseline_id else None,
        }

    async def _baseline(
        self,
        schedule: Any,
        doc: MspdiDocument,
        by_uid: dict[str, Any],
        rels: list[Any],
        user_id: str,
        filename: str,
    ) -> uuid.UUID | None:
        """Baseline 0 of the file as the next unapproved programme baseline (B<n>)."""
        from app.modules.schedule.models import ScheduleBaseline
        from app.modules.schedule.snapshot_envelope import live_envelope

        rows = []
        for task in doc.tasks:
            if not (task.baseline_start and task.baseline_finish):
                continue
            act = by_uid[task.uid]
            rows.append(
                SimpleNamespace(
                    id=act.id,
                    wbs_code=act.wbs_code,
                    name=act.name,
                    parent_id=act.parent_id,
                    start_date=task.baseline_start,
                    end_date=task.baseline_finish,
                    duration_days=task.baseline_duration_days,
                    constraint_type=act.constraint_type,
                    constraint_date=act.constraint_date,
                    calendar_id=act.calendar_id,
                )
            )
        if not rows:
            return None
        existing = await self.session.execute(
            select(ScheduleBaseline.name).where(ScheduleBaseline.schedule_id == schedule.id)
        )
        label = next_baseline_label(existing.scalars().all())
        now = datetime.now(UTC)
        keep = {r.id for r in rows}
        baseline = ScheduleBaseline(
            schedule_id=schedule.id,
            project_id=schedule.project_id,
            name=label,
            baseline_date=now.date().isoformat(),
            snapshot_data=live_envelope(rows, [r for r in rels if r.predecessor_id in keep and r.successor_id in keep]),
            is_active=False,
            created_by=uuid.UUID(user_id),
            metadata_={
                "kind": "programme_baseline",
                "label": label,
                "source": "msp_xml_import",
                "source_filename": filename[:255],
                "captured_by": user_id,
                "captured_at": now.isoformat(timespec="seconds"),
                "activity_count": len(rows),
            },
        )
        self.session.add(baseline)
        await self.session.flush()
        return baseline.id
