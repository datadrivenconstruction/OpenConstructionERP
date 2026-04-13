"""ERP Chat message vector adapter — feeds the ``oe_chat`` collection.

Indexes the textual ``content`` field of every chat message so the
AI advisor and global semantic search can recall past conversations
("show me messages where we discussed the basement waterproofing
budget").

System and tool messages are skipped — only user and assistant turns
carry the kind of free-text the user might want to search later.

Implements the :class:`~app.core.vector_index.EmbeddingAdapter`
protocol.
"""

from __future__ import annotations

from typing import Any

from app.core.vector_index import COLLECTION_CHAT
from app.modules.erp_chat.models import ChatMessage

_INDEXABLE_ROLES = {"user", "assistant"}


class ChatMessageAdapter:
    """Embed chat messages into the unified vector store."""

    collection_name: str = COLLECTION_CHAT
    module_name: str = "chat"

    def to_text(self, row: ChatMessage) -> str:
        """Return the message body, or empty string if it should be skipped.

        We skip messages whose role is not user/assistant (system + tool
        rows are infrastructure noise) and any row with empty content.
        """
        if (row.role or "").lower() not in _INDEXABLE_ROLES:
            return ""
        content = (row.content or "").strip()
        return content

    def to_payload(self, row: ChatMessage) -> dict[str, Any]:
        """Lightweight payload for hit cards.

        ``title`` is the first ~120 characters of the content so the
        global Cmd+Shift+K modal can render a useful preview without an
        extra DB roundtrip.
        """
        content = (row.content or "").strip()
        return {
            "title": content[:120] or f"{row.role or 'message'} message",
            "role": row.role or "",
            "session_id": str(row.session_id) if row.session_id else "",
        }

    def project_id_of(self, row: ChatMessage) -> str | None:
        """Resolve project_id via the parent ChatSession.

        ``project_id`` is optional on a session, so this returns ``None``
        for tenant-wide chats — those still get indexed but won't show
        up in project-scoped search results.
        """
        session = getattr(row, "session", None)
        if session is not None and getattr(session, "project_id", None):
            return str(session.project_id)
        return None


chat_message_adapter = ChatMessageAdapter()
