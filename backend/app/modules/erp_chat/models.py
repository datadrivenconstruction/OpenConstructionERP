# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
from __future__ import annotations

"""ERP Chat ORM models.

Tables:
    oe_erp_chat_session         - chat session per user, optionally scoped to a project
    oe_erp_chat_message         - individual messages within a session (user/assistant/tool/system)
    oe_erp_chat_turn_feedback   - per-(message, user) thumbs up/down feedback (T8)
    oe_erp_chat_action          - a change the assistant proposed and what a person decided about it
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
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
    """User-supplied thumbs up/down on a single assistant message.

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


class ChatAction(Base):
    """A change the assistant proposed, and what a person decided about it.

    The assistant never writes a domain record itself. A write tool persists
    one of these rows with status ``proposed`` and nothing else; the record it
    describes is created or changed only when a person applies the row, under
    the same gates the record's own REST route runs for that person. The row
    then keeps the whole story: who asked, what the model proposed
    (``original_payload``, never mutated), what the person changed before
    applying (``payload``), who approved and when, which record it produced,
    and whether it was undone.

    Statuses: ``proposed`` -> ``applied`` | ``rejected`` | ``failed``;
    ``failed`` -> ``applied`` (retry) | ``rejected``; ``applied`` -> ``reverted``.

    ``session_id`` is ``ON DELETE SET NULL`` rather than CASCADE on purpose:
    deleting a conversation must not erase the record of a change that reached
    the project. ``message_id`` carries no FK because the assistant message is
    written only when the turn ends, after its proposals already exist.
    """

    __tablename__ = "oe_erp_chat_action"

    session_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_erp_chat_session.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    requested_by: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="proposed",
        server_default="proposed",
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    original_payload: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    payload: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    preview: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    rationale: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    before_state: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    applied_entity_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    applied_entity_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reverted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revert_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<ChatAction {self.id} {self.action_type} {self.status}>"
