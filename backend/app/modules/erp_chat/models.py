from __future__ import annotations

"""ERP Chat ORM models.

Tables:
    oe_erp_chat_session  — chat session per user, optionally scoped to a project
    oe_erp_chat_message  — individual messages within a session (user/assistant/tool/system)
"""

import uuid

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class ChatSession(Base):
    """A single chat session between a user and the ERP AI assistant."""

    __tablename__ = "oe_erp_chat_session"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="New Chat")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # Relationships
    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="ChatMessage.created_at",
    )

    def __repr__(self) -> str:
        return f"<ChatSession {self.id} user={self.user_id}>"


class ChatMessage(Base):
    """A single message in a chat session."""

    __tablename__ = "oe_erp_chat_message"

    session_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_erp_chat_session.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)
    tool_calls: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tool_results: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    renderer: Mapped[str | None] = mapped_column(String(50), nullable=True)
    renderer_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Relationships
    session: Mapped[ChatSession] = relationship(back_populates="messages")

    def __repr__(self) -> str:
        return f"<ChatMessage {self.id} role={self.role}>"
