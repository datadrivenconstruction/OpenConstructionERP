"""AI Estimation ORM models.

Tables:
    oe_ai_settings — per-user AI provider configuration (API keys, preferred model)
    oe_ai_estimate_job — tracks AI estimation requests and results
"""

import uuid

from sqlalchemy import ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class AISettings(Base):
    """Per-user AI configuration — API keys and model preferences."""

    __tablename__ = "oe_ai_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    anthropic_api_key: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None
    )
    openai_api_key: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None
    )
    gemini_api_key: Mapped[str | None] = mapped_column(
        String(500), nullable=True, default=None
    )
    preferred_model: Mapped[str] = mapped_column(
        String(100), nullable=False, default="claude-sonnet"
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<AISettings user={self.user_id} model={self.preferred_model}>"


class AIEstimateJob(Base):
    """Tracks an AI estimation request — input, status, and result."""

    __tablename__ = "oe_ai_estimate_job"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    input_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="text"
    )
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50), nullable=False, default="pending"
    )
    result: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True, default=None
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<AIEstimateJob {self.id} ({self.status})>"
