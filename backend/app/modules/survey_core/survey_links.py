# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Links from a survey record to the site diary and to documents.

A traverse or level run (``SurveyTraverse``) or an import (``SurveyPointSet``)
is linked to:

* the site diary of its day: a ``daily_diary`` entry with ``source_module``
  ``survey_core`` and ``source_ref`` the record id, carrying crew, instrument and
  weather. The diary shows it with a link back; this side lists the entries.
* documents and photos: ``file_references`` rows with target type
  ``survey_traverse`` or ``survey_point_set``. The document preview lists the
  record; this side lists the files.

No new table: both halves reuse the modules that own them.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.survey_core.calc_schemas import (
    DiaryLinkIn,
    DiaryLinkOut,
    DocumentLinkOut,
    SurveyLinkKind,
    SurveyLinksOut,
)
from app.modules.survey_core.models import SurveyPointSet, SurveyTraverse

SOURCE_MODULE = "survey_core"
TARGET_TYPES: dict[str, str] = {"traverse": "survey_traverse", "point_set": "survey_point_set"}
DIARY_ENTRY_TYPE = "event"


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


class SurveyLinkService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def _target(self, project_id: uuid.UUID, kind: SurveyLinkKind, target_id: uuid.UUID) -> object:
        model = SurveyTraverse if kind == "traverse" else SurveyPointSet
        row = await self.session.get(model, target_id)
        if row is None or row.project_id != project_id:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Survey record not found")
        return row

    async def links(self, project_id: uuid.UUID, kind: SurveyLinkKind, target_id: uuid.UUID) -> SurveyLinksOut:
        """Diary entries and files linked to one survey record."""
        await self._target(project_id, kind, target_id)
        out = SurveyLinksOut(kind=kind, target_id=str(target_id))
        try:
            from app.modules.daily_diary.models import DailyDiary, DiaryEntry  # noqa: PLC0415
        except ImportError:  # module not installed
            DailyDiary = DiaryEntry = None  # type: ignore[assignment,misc]  # noqa: N806
        if DiaryEntry is not None:
            found = await self.session.execute(
                select(DiaryEntry, DailyDiary.diary_date)
                .join(DailyDiary, DailyDiary.id == DiaryEntry.diary_id)
                .where(
                    DailyDiary.project_id == project_id,
                    DiaryEntry.source_module == SOURCE_MODULE,
                    DiaryEntry.source_ref == target_id,
                )
                .order_by(DailyDiary.diary_date)
            )
            for entry, day in found.all():
                meta = entry.metadata_ or {}
                out.diary.append(
                    DiaryLinkOut(
                        entry_id=str(entry.id),
                        diary_id=str(entry.diary_id),
                        diary_date=str(day),
                        title=entry.title,
                        crew=str(meta.get("crew") or ""),
                        instrument=str(meta.get("instrument") or ""),
                        weather=str(meta.get("weather") or ""),
                    )
                )
        try:
            from app.modules.file_references.models import FileReference  # noqa: PLC0415
        except ImportError:
            return out
        refs = await self.session.execute(
            select(FileReference)
            .where(
                FileReference.project_id == project_id,
                FileReference.target_type == TARGET_TYPES[kind],
                FileReference.target_id == str(target_id),
            )
            .order_by(FileReference.created_at)
        )
        rows = list(refs.scalars())
        names = await self._file_names(rows)
        out.documents = [
            DocumentLinkOut(
                reference_id=str(r.id), file_kind=r.file_kind, file_id=r.file_id, label=names.get(r.file_id, "")
            )
            for r in rows
        ]
        return out

    async def _file_names(self, refs: list) -> dict[str, str]:
        """File names of linked documents and photos, so the list reads as files, not ids."""
        try:
            from app.modules.documents.models import Document, ProjectPhoto  # noqa: PLC0415
        except ImportError:
            return {}
        names: dict[str, str] = {}
        doc_ids = [u for r in refs if r.file_kind == "document" and (u := _uuid(r.file_id))]
        photo_ids = [u for r in refs if r.file_kind == "photo" and (u := _uuid(r.file_id))]
        if doc_ids:
            for doc_id, name in await self.session.execute(
                select(Document.id, Document.name).where(Document.id.in_(doc_ids))
            ):
                names[str(doc_id)] = name
        if photo_ids:
            found = await self.session.execute(
                select(ProjectPhoto.id, ProjectPhoto.caption, ProjectPhoto.filename).where(
                    ProjectPhoto.id.in_(photo_ids)
                )
            )
            for photo_id, caption, filename in found:
                names[str(photo_id)] = caption or filename
        return names

    async def link_diary(
        self, project_id: uuid.UUID, kind: SurveyLinkKind, target_id: uuid.UUID, body: DiaryLinkIn, user_id: str
    ) -> DiaryLinkOut:
        """Record the survey in the diary of its day; the day's diary is opened when there is none."""
        await self._target(project_id, kind, target_id)
        try:
            from app.modules.daily_diary.schemas import DailyDiaryCreate, DiaryEntryCreate  # noqa: PLC0415
            from app.modules.daily_diary.service import DailyDiaryService  # noqa: PLC0415
        except ImportError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The site diary is not installed") from exc
        diaries = DailyDiaryService(self.session)
        diary = await diaries.diary_repo.get_by_date_and_project(project_id, body.diary_date)
        if diary is None:
            diary = await diaries.create_diary(
                DailyDiaryCreate(
                    project_id=project_id,
                    diary_date=body.diary_date,
                    weather_summary={"conditions_text": body.weather} if body.weather else {},
                ),
                user_id,
            )
        day = datetime.strptime(body.diary_date, "%Y-%m-%d").replace(hour=12, tzinfo=UTC)
        meta = {"kind": kind, "crew": body.crew, "instrument": body.instrument, "weather": body.weather}
        entry = await diaries.create_entry(
            DiaryEntryCreate(
                diary_id=diary.id,
                entry_type=DIARY_ENTRY_TYPE,
                entry_time=day,
                title=body.title,
                description=body.note or None,
                source_module=SOURCE_MODULE,
                source_ref=target_id,
                author_id=_uuid(user_id),
                metadata=meta,
            )
        )
        return DiaryLinkOut(
            entry_id=str(entry.id),
            diary_id=str(diary.id),
            diary_date=body.diary_date,
            title=entry.title,
            crew=body.crew,
            instrument=body.instrument,
            weather=body.weather,
        )


__all__ = ["SOURCE_MODULE", "TARGET_TYPES", "SurveyLinkService"]
