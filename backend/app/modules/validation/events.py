"""Validation event handlers — vector indexing.

Subscribes to validation.report.* events and keeps the
``oe_validation`` vector collection in sync with the underlying
ValidationReport rows.
"""

from __future__ import annotations

import logging
import uuid

from app.core.events import Event, event_bus
from app.core.vector_index import delete_one as vector_delete_one
from app.core.vector_index import index_one as vector_index_one
from app.database import async_session_factory
from app.modules.validation.models import ValidationReport
from app.modules.validation.vector_adapter import validation_report_adapter

logger = logging.getLogger(__name__)


async def _index_report(event: Event) -> None:
    rid_raw = (event.data or {}).get("report_id")
    if not rid_raw:
        return
    try:
        report_id = uuid.UUID(str(rid_raw))
    except (ValueError, AttributeError):
        return
    try:
        async with async_session_factory() as session:
            row = await session.get(ValidationReport, report_id)
            if row is None:
                await vector_delete_one(validation_report_adapter, str(report_id))
                return
            project_id = str(row.project_id) if row.project_id else None
            await vector_index_one(
                validation_report_adapter,
                row,
                project_id=project_id,
            )
    except Exception:
        logger.debug("Validation vector index failed for %s", rid_raw, exc_info=True)


async def _delete_report_vector(event: Event) -> None:
    rid_raw = (event.data or {}).get("report_id")
    if not rid_raw:
        return
    try:
        await vector_delete_one(validation_report_adapter, str(rid_raw))
    except Exception:
        logger.debug("Validation vector delete failed for %s", rid_raw, exc_info=True)


async def _on_report_created(event: Event) -> None:
    await _index_report(event)


async def _on_report_updated(event: Event) -> None:
    await _index_report(event)


async def _on_report_deleted(event: Event) -> None:
    await _delete_report_vector(event)


event_bus.subscribe("validation.report.created", _on_report_created)
event_bus.subscribe("validation.report.updated", _on_report_updated)
event_bus.subscribe("validation.report.deleted", _on_report_deleted)
