# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""AI Estimation ORM models.

Tables:
    oe_ai_settings - per-user AI provider configuration (API keys, preferred model)
    oe_ai_estimate_job - tracks AI estimation requests and results
"""

import uuid
from typing import Any

from sqlalchemy import JSON, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class AISettings(Base):
    """Per-user AI configuration - API keys and model preferences."""

    __tablename__ = "oe_ai_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        unique=True,
        index=True,
    )
    anthropic_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    openai_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    gemini_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    kimi_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    openrouter_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    mistral_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    groq_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    deepseek_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    together_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    fireworks_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    perplexity_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    cohere_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    ai21_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    xai_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    zhipu_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    baidu_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    yandex_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    gigachat_api_key: Mapped[str | None] = mapped_column(String(500), nullable=True, default=None)
    preferred_model: Mapped[str] = mapped_column(String(100), nullable=False, default="claude-sonnet")
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    # The key of the self-hosted OpenAI-compatible endpoint (provider id
    # "vllm", issue #499) lives in ``metadata`` rather than in a column, so an
    # upgraded install needs no schema change. Like the columns above it holds
    # Fernet ciphertext; the property keeps every ``f"{provider}_api_key"``
    # reader working unchanged.
    @property
    def vllm_api_key(self) -> str | None:
        """Ciphertext of the endpoint key, or None when none is stored."""
        meta = self.metadata_ if isinstance(self.metadata_, dict) else {}
        value = meta.get(VLLM_API_KEY_META)
        return value if isinstance(value, str) and value else None

    @vllm_api_key.setter
    def vllm_api_key(self, ciphertext: str | None) -> None:
        # A new dict, never an in-place edit: a plain JSON column does not
        # track mutation, so changing the existing dict would not be saved.
        self.metadata_ = with_vllm_api_key(self.metadata_, ciphertext)

    def __repr__(self) -> str:
        return f"<AISettings user={self.user_id} model={self.preferred_model}>"


#: ``metadata`` key holding the endpoint key ciphertext. Never echoed to clients.
VLLM_API_KEY_META = "vllm_api_key"


def with_vllm_api_key(metadata: Any, ciphertext: str | None) -> dict[str, Any]:
    """Return a copy of *metadata* holding *ciphertext*, or without it when empty."""
    merged: dict[str, Any] = dict(metadata) if isinstance(metadata, dict) else {}
    if ciphertext:
        merged[VLLM_API_KEY_META] = ciphertext
    else:
        merged.pop(VLLM_API_KEY_META, None)
    return merged


class AIEstimateJob(Base):
    """Tracks an AI estimation request - input, status, and result."""

    __tablename__ = "oe_ai_estimate_job"

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
    input_type: Mapped[str] = mapped_column(String(50), nullable=False, default="text")
    input_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    input_filename: Mapped[str | None] = mapped_column(String(500), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pending")
    result: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=True, default=None
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    model_used: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tokens_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Estimated USD spend for this job - computed at persist time from
    # ``tokens_used`` and the shared rate table in
    # :mod:`app.core.ai.pricing`. Float (not Numeric) for symmetry with
    # ``clash_ai_triage`` and so SQLite happily stores it as REAL.
    cost_usd_estimate: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.0,
        server_default="0.0",
    )

    def __repr__(self) -> str:
        return f"<AIEstimateJob {self.id} ({self.status})>"
