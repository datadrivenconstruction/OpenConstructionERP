"""ERP Chat event handlers — vector indexing.

Subscribes to ``erp_chat.message.*`` events and keeps the ``oe_chat``
vector collection in sync with persisted ChatMessage rows.

Only user / assistant messages with non-empty content actually get
embedded — the adapter drops everything else.
"""

from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import selectinload

from app.core.events import Event, event_bus
from app.core.vector_index import delete_one as vector_delete_one
from app.core.vector_index import index_one as vector_index_one
from app.database import async_session_factory
from app.modules.erp_chat.models import ChatMessage
from app.modules.erp_chat.vector_adapter import chat_message_adapter

logger = logging.getLogger(__name__)


async def _index_message(event: Event) -> None:
    mid_raw = (event.data or {}).get("message_id")
    if not mid_raw:
        return
    try:
        message_id = uuid.UUID(str(mid_raw))
    except (ValueError, AttributeError):
        return

    project_id_payload = (event.data or {}).get("project_id")
    project_id = project_id_payload if isinstance(project_id_payload, str) else None

    try:
        async with async_session_factory() as session:
            # Eager-load the parent session so the adapter can resolve the
            # project id without a second query.
            from sqlalchemy import select

            stmt = (
                select(ChatMessage)
                .options(selectinload(ChatMessage.session))
                .where(ChatMessage.id == message_id)
            )
            row = (await session.execute(stmt)).scalar_one_or_none()
            if row is None:
                await vector_delete_one(chat_message_adapter, str(message_id))
                return
            await vector_index_one(
                chat_message_adapter,
                row,
                project_id=project_id,
            )
    except Exception:
        logger.debug("Chat vector index failed for %s", mid_raw, exc_info=True)


async def _delete_message_vector(event: Event) -> None:
    mid_raw = (event.data or {}).get("message_id")
    if not mid_raw:
        return
    try:
        await vector_delete_one(chat_message_adapter, str(mid_raw))
    except Exception:
        logger.debug("Chat vector delete failed for %s", mid_raw, exc_info=True)


async def _on_message_created(event: Event) -> None:
    await _index_message(event)


async def _on_message_deleted(event: Event) -> None:
    await _delete_message_vector(event)


event_bus.subscribe("erp_chat.message.created", _on_message_created)
event_bus.subscribe("erp_chat.message.deleted", _on_message_deleted)
