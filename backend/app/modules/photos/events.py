# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Photos module events.

Published (all after commit, ``source_module="oe_photos"``):
    photos.photo.created | photos.photo.updated | photos.photo.archived
    photos.link.added | photos.ai.suggested | photos.ai.accepted

Subscribed, to index photos other modules hold as soon as they appear:
    daily_diary.photo.registered      - one diary photo row
    punchlist.item.created / updated  - the item's ``photos`` list
    punchlist.item.deleted            - archive the item's index rows
    fieldreports.report.submitted     - the report's ``photos`` list

Progress entries, inspections and safety observations publish no photo event;
their photos are picked up by the backfill job.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from app.core.events import Event, event_bus

logger = logging.getLogger(__name__)

#: event name -> (source module, ORM model path, payload key of the record id)
_INDEXED: dict[str, tuple[str, str, str]] = {
    "daily_diary.photo.registered": ("daily_diary", "app.modules.daily_diary.models:DiaryPhoto", "photo_id"),
    "punchlist.item.created": ("punchlist", "app.modules.punchlist.models:PunchItem", "item_id"),
    "punchlist.item.updated": ("punchlist", "app.modules.punchlist.models:PunchItem", "item_id"),
    "fieldreports.report.submitted": ("fieldreports", "app.modules.fieldreports.models:FieldReport", "report_id"),
}


def _uuid(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError):
        return None


async def index_from_event(event: Event) -> int:
    """Index the photos of the record an event names. Fail-soft; returns rows created."""
    spec = _INDEXED.get(event.name)
    if spec is None:
        return 0
    source_module, model_path, id_key = spec
    data = event.data or {}
    record_id = _uuid(data.get(id_key))
    if record_id is None:
        return 0
    try:
        from app.database import async_session_factory
        from app.modules.photos.jobs import build_pending_thumbnails
        from app.modules.photos.service import PhotosService, _row_dict

        module_name, cls_name = model_path.split(":")
        model = getattr(__import__(module_name, fromlist=[cls_name]), cls_name)
        async with async_session_factory() as session:
            row = await session.get(model, record_id)
            if row is None:
                return 0
            project_id = row.project_id
            created = await PhotosService(session).index_source_record(project_id, source_module, _row_dict(row))
            await session.commit()
        if created:
            await build_pending_thumbnails(project_id)
        return created
    except Exception:  # noqa: BLE001 - indexing must never break the publishing module
        logger.warning("photos: indexing from %s failed", event.name, exc_info=True)
        return 0


async def archive_from_event(event: Event) -> int:
    """``punchlist.item.deleted``: the item's photos leave the archive views, rows stay for history."""
    data = event.data or {}
    project_id, item_id = _uuid(data.get("project_id")), _uuid(data.get("item_id"))
    if project_id is None or item_id is None:
        return 0
    try:
        from app.database import async_session_factory
        from app.modules.photos.service import PhotosService

        async with async_session_factory() as session:
            count = await PhotosService(session).archive_source(project_id, "punchlist", str(item_id))
            await session.commit()
        return count
    except Exception:  # noqa: BLE001 - fail soft
        logger.warning("photos: archiving punch item photos failed", exc_info=True)
        return 0


def register_photos_event_subscribers() -> None:
    """Wire the indexing subscribers. Idempotent."""
    for name in _INDEXED:
        event_bus.subscribe_once(name, index_from_event)
    event_bus.subscribe_once("punchlist.item.deleted", archive_from_event)
