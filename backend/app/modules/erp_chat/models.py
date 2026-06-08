from __future__ import annotations

"""‌⁠‍ERP Chat ORM models.

Tables:
    oe_erp_chat_session         - chat session per user, optionally scoped to a project
    oe_erp_chat_message         - individual messages within a session (user/assistant/tool/system)
    oe_erp_chat_turn_feedback   - per-(message, user) thumbs up/down feedback (T8)
"""

import uuid

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class ChatSession(Base):
    """‌⁠‍A single chat session between a user and the ERP AI assistant."""

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
    """‌⁠‍A single message in a chat session."""

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

    # ── Per-turn observability (T8 / v3089) ─────────────────────────────
    # These supplement the legacy ``tokens_used`` total with the split
    # input/output breakdown construction AI assistants surface in their
    # admin dashboards, plus prompt-cache hit + wall-clock latency. All
    # four are nullable because older rows pre-date the migration.
    tokens_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tokens_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_hit: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Relationships
    session: Mapped[ChatSession] = relationship(back_populates="messages")
    feedback: Mapped[list[ChatTurnFeedback]] = relationship(
        back_populates="message",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<ChatMessage {self.id} role={self.role}>"


class ChatTurnFeedback(Base):
    """‌⁠‍User-supplied thumbs up/down on a single assistant message.

    One row per ``(message_id, user_id)``. Re-submitting on the same
    pair updates the rating in place - see
    :meth:`ERPChatService.submit_feedback`.
    """

    __tablename__ = "oe_erp_chat_turn_feedback"
    __table_args__ = (
        UniqueConstraint(
            "message_id",
            "user_id",
            name="uq_oe_erp_chat_turn_feedback_message_user",
        ),
        CheckConstraint(
            "rating IN (-1, 1)",
            name="ck_oe_erp_chat_turn_feedback_rating",
        ),
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_erp_chat_message.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)

    message: Mapped[ChatMessage] = relationship(back_populates="feedback")

    def __repr__(self) -> str:
        return f"<ChatTurnFeedback {self.id} msg={self.message_id} r={self.rating}>"
