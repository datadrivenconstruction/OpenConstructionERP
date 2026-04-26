"""Pydantic schemas for the Background Jobs status module."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class JobRunRead(BaseModel):
    """Read-only view of a JobRun row.

    Mirrors the columns on :class:`app.core.job_run.JobRun` that are
    safe and useful to expose over HTTP. Mutating fields (payload,
    celery_task_id) are intentionally omitted from the public surface
    to keep the contract tight.
    """

    id: UUID
    kind: str
    status: str = Field(
        description=(
            "One of: pending, started, success, failed, cancelled, retry."
        ),
    )
    progress_percent: int = Field(ge=0, le=100, default=0)
    result: dict[str, Any] | None = Field(
        default=None,
        description="Handler return value once status='success'.",
    )
    error: dict[str, Any] | None = Field(
        default=None,
        description="{type, message, traceback} once status='failed'.",
    )
    started_at: datetime | None = None
    completed_at: datetime | None = None
    retry_count: int = 0
    idempotency_key: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    tenant_id: UUID | None = None

    model_config = {"from_attributes": True}


class JobRunListResponse(BaseModel):
    """Paginated list payload for ``GET /jobs``."""

    items: list[JobRunRead]
    total: int
    limit: int
    offset: int
    has_more: bool = False
