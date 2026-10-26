# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Keep what a schedule was imported from.

Every file importer (XER, MSPDI XML, spreadsheet) calls
:meth:`ImportSourceService.record_import` once its activities are written:

* the original file is stored in the project's documents, tagged and linked
  to the schedule, so the source of a programme can always be produced;
* each imported activity keeps the dates it had in the file in
  ``Activity.metadata_["source_dates"]``;
* the schedule records the import in ``Schedule.metadata_["import_source"]``.

Until the user accepts the recalculated dates the schedule screen shows
"dates as in source" beside the current dates with the deviation in days
(:meth:`ImportSourceService.comparison`). Accepting closes the comparison and
keeps the record; restoring puts the source dates back.

:func:`stable_export_uids` keeps the identifiers a file came with when the
schedule is exported again, so a re-exported programme matches the original
row for row.
"""

from __future__ import annotations

import hashlib
import io
import logging
import uuid
from collections.abc import Iterable
from datetime import UTC, date, datetime
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers

from app.core.audit_log import log_activity
from app.modules.schedule.models import Activity, Schedule

logger = logging.getLogger(__name__)

SOURCE_DATES_KEY = "source_dates"
IMPORT_SOURCE_KEY = "import_source"
SOURCE_DOCUMENT_TAG = "schedule-import-source"
#: Metadata keys importers store a source identifier under, in lookup order.
SOURCE_ID_KEYS: tuple[str, ...] = ("msp_uid", "xer_task_id", "import_row")
_MEDIA_TYPES = {"xer": "text/plain", "msp_xml": "application/xml", "spreadsheet": "application/octet-stream"}


def _day(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def deviation_days(source: object, current: object) -> int | None:
    """Calendar days from the source date to the current one, ``None`` when either is missing."""
    s, c = _day(source), _day(current)
    if s is None or c is None:
        return None
    return (c - s).days


def source_id_of(metadata: object) -> str | None:
    """The identifier the activity had in its source file, if any."""
    if not isinstance(metadata, dict):
        return None
    for key in SOURCE_ID_KEYS:
        value = metadata.get(key)
        if value not in (None, ""):
            return str(value)
    return None


def stable_export_uids(activities: Iterable[Any]) -> dict[str, int]:
    """Map activity id -> positive integer UID for an MSPDI export.

    An activity imported from MSPDI keeps its ``msp_uid`` and one imported from
    XER keeps its numeric ``xer_task_id``, so exporting again reproduces the
    file's identifiers. Activities without one, and any duplicate, get fresh
    numbers above the highest kept one, in list order.
    """
    rows = list(activities)
    uids: dict[str, int] = {}
    used: set[int] = set()
    for act in rows:
        meta = getattr(act, "metadata_", None)
        if not isinstance(meta, dict):
            continue
        for key in ("msp_uid", "xer_task_id"):
            raw = meta.get(key)
            try:
                candidate = int(str(raw))
            except (TypeError, ValueError):
                continue
            if candidate > 0 and candidate not in used:
                uids[str(act.id)] = candidate
                used.add(candidate)
                break
    next_uid = max(used, default=0) + 1
    for act in rows:
        if str(act.id) not in uids:
            uids[str(act.id)] = next_uid
            next_uid += 1
    return uids


class ImportSourceService:
    """Record, compare, accept and restore the source of an imported schedule."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _store_document(
        self, schedule: Schedule, raw: bytes, filename: str, fmt: str, user_id: str
    ) -> tuple[uuid.UUID | None, str | None]:
        """Store the file in the project's documents; ``(None, reason)`` when it cannot be."""
        try:
            from app.modules.documents.service import DocumentService
        except ImportError:  # documents module not installed
            return None, "documents_module_unavailable"
        upload = UploadFile(
            file=io.BytesIO(raw),
            filename=filename or f"schedule-source.{fmt}",
            size=len(raw),
            headers=Headers({"content-type": _MEDIA_TYPES.get(fmt, "application/octet-stream")}),
        )
        try:
            async with self.session.begin_nested():
                document = await DocumentService(self.session).upload_document(
                    schedule.project_id, upload, "other", str(user_id)
                )
                document.tags = sorted({*(document.tags or []), "schedule", SOURCE_DOCUMENT_TAG})
                document.description = f"Source file of schedule {schedule.name}"
                document.metadata_ = {
                    **(document.metadata_ or {}),
                    "linked_entity": {"type": "schedule", "id": str(schedule.id)},
                    "schedule_import_format": fmt,
                }
                await self.session.flush()
                return document.id, None
        except HTTPException as exc:
            logger.warning("Schedule %s: source file not stored: %s", schedule.id, exc.detail)
            return None, "document_rejected"

    async def record_import(
        self,
        schedule_id: uuid.UUID,
        *,
        raw: bytes,
        filename: str,
        fmt: str,
        user_id: str,
        activity_ids: Iterable[uuid.UUID] | None = None,
    ) -> dict[str, Any]:
        """Store the file, snapshot source dates of the imported activities, record the import.

        ``activity_ids`` names the activities this import created; ``None``
        means every activity of the schedule (an import into a new schedule).
        Returns the stored ``import_source`` record.
        """
        schedule = await self.session.get(Schedule, schedule_id)
        if schedule is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
        stmt = select(Activity).where(Activity.schedule_id == schedule_id)
        if activity_ids is not None:
            ids = list(activity_ids)
            stmt = stmt.where(Activity.id.in_(ids)) if ids else stmt.where(Activity.id.is_(None))
        activities = list((await self.session.execute(stmt)).scalars().all())
        for act in activities:
            meta = dict(act.metadata_ or {})
            meta[SOURCE_DATES_KEY] = {
                "start": act.start_date,
                "finish": act.end_date,
                "duration_days": act.duration_days,
            }
            act.metadata_ = meta
        document_id, store_issue = await self._store_document(schedule, raw, filename, fmt, user_id)
        record = {
            "format": fmt,
            "filename": filename,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "size_bytes": len(raw),
            "document_id": str(document_id) if document_id else None,
            "document_issue": store_issue,
            "imported_at": datetime.now(UTC).isoformat(),
            "imported_by": str(user_id) if user_id else None,
            "activity_count": len(activities),
            "status": "pending_review",
            "accepted_at": None,
            "accepted_by": None,
        }
        schedule = await self.session.get(Schedule, schedule_id)
        assert schedule is not None
        meta = dict(schedule.metadata_ or {})
        meta[IMPORT_SOURCE_KEY] = record
        schedule.metadata_ = meta
        await self.session.flush()
        await log_activity(
            self.session,
            actor_id=user_id,
            entity_type="schedule",
            entity_id=schedule_id,
            action="imported_from_file",
            module="oe_schedule",
            metadata={k: record[k] for k in ("format", "filename", "sha256", "document_id", "activity_count")},
        )
        return record

    async def _schedule_with_source(self, schedule_id: uuid.UUID) -> tuple[Schedule, dict[str, Any]]:
        schedule = await self.session.get(Schedule, schedule_id)
        if schedule is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Schedule not found")
        record = (schedule.metadata_ or {}).get(IMPORT_SOURCE_KEY)
        if not isinstance(record, dict):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"code": "schedule_not_imported", "message": "This schedule was not imported from a file"},
            )
        return schedule, record

    async def comparison(self, schedule_id: uuid.UUID) -> dict[str, Any]:
        """Source dates beside current dates for every activity that carries them."""
        schedule, record = await self._schedule_with_source(schedule_id)
        stmt = select(Activity).where(Activity.schedule_id == schedule_id).order_by(Activity.sort_order)
        rows: list[dict[str, Any]] = []
        source_finish: str | None = None
        current_finish: str | None = None
        for act in (await self.session.execute(stmt)).scalars().all():
            meta = act.metadata_ if isinstance(act.metadata_, dict) else {}
            src = meta.get(SOURCE_DATES_KEY)
            if not isinstance(src, dict):
                continue
            start_dev = deviation_days(src.get("start"), act.start_date)
            finish_dev = deviation_days(src.get("finish"), act.end_date)
            if src.get("finish") and (source_finish is None or str(src["finish"]) > source_finish):
                source_finish = str(src["finish"])
            if act.end_date and (current_finish is None or act.end_date > current_finish):
                current_finish = act.end_date
            rows.append(
                {
                    "activity_id": act.id,
                    "activity_code": act.activity_code,
                    "name": act.name,
                    "source_id": source_id_of(meta),
                    "source_start": src.get("start"),
                    "source_finish": src.get("finish"),
                    "source_duration_days": src.get("duration_days"),
                    "current_start": act.start_date,
                    "current_finish": act.end_date,
                    "current_duration_days": act.duration_days,
                    "start_deviation_days": start_dev,
                    "finish_deviation_days": finish_dev,
                }
            )
        deviating = [r for r in rows if r["start_deviation_days"] or r["finish_deviation_days"]]
        return {
            "schedule_id": schedule.id,
            "source": record,
            "activity_count": len(rows),
            "deviating_count": len(deviating),
            "max_finish_deviation_days": max((abs(r["finish_deviation_days"] or 0) for r in rows), default=0),
            "source_finish": source_finish,
            "current_finish": current_finish,
            "project_finish_deviation_days": deviation_days(source_finish, current_finish),
            "activities": rows,
        }

    async def accept(self, schedule_id: uuid.UUID, user_id: str) -> dict[str, Any]:
        """Accept the recalculated dates; the comparison closes, the record stays."""
        schedule, record = await self._schedule_with_source(schedule_id)
        summary = await self.comparison(schedule_id)
        record = {
            **record,
            "status": "accepted",
            "accepted_at": datetime.now(UTC).isoformat(),
            "accepted_by": str(user_id) if user_id else None,
            "deviating_at_acceptance": summary["deviating_count"],
        }
        meta = dict(schedule.metadata_ or {})
        meta[IMPORT_SOURCE_KEY] = record
        schedule.metadata_ = meta
        await self.session.flush()
        await log_activity(
            self.session,
            actor_id=user_id,
            entity_type="schedule",
            entity_id=schedule_id,
            action="import_recalculation_accepted",
            module="oe_schedule",
            metadata={"deviating_count": summary["deviating_count"], "document_id": record.get("document_id")},
        )
        return record

    async def restore(self, schedule_id: uuid.UUID, user_id: str) -> int:
        """Put every activity back on its source dates; returns how many moved."""
        schedule, record = await self._schedule_with_source(schedule_id)
        if record.get("status") == "accepted":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "import_already_accepted", "message": "The recalculated dates were accepted"},
            )
        stmt = select(Activity).where(Activity.schedule_id == schedule_id)
        moved = 0
        for act in (await self.session.execute(stmt)).scalars().all():
            src = (act.metadata_ or {}).get(SOURCE_DATES_KEY) if isinstance(act.metadata_, dict) else None
            if not isinstance(src, dict) or not src.get("start") or not src.get("finish"):
                continue
            if (act.start_date, act.end_date) == (src["start"], src["finish"]):
                continue
            act.start_date = str(src["start"])
            act.end_date = str(src["finish"])
            if isinstance(src.get("duration_days"), int):
                act.duration_days = src["duration_days"]
            moved += 1
        await self.session.flush()
        await log_activity(
            self.session,
            actor_id=user_id,
            entity_type="schedule",
            entity_id=schedule.id,
            action="import_source_dates_restored",
            module="oe_schedule",
            metadata={"moved": moved},
        )
        return moved
