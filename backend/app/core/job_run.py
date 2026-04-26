# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""``oe_job_run`` ORM model — RFC 34 §4 W0.1.

The JobRun row records every background task we hand off to Celery.
It exists for three reasons:

1. **Idempotency** — the unique ``idempotency_key`` lets multiple callers
   race the same submission without duplicating work.
2. **Observability** — status / progress / result / error are visible to
   the UI without coupling to Celery's own result backend.
3. **Replay** — once stored we can re-dispatch a stuck row without losing
   the original payload or audit trail.

The schema mirrors the validation report pattern (``oe_validation_report``)
to stay consistent with the rest of the platform's table conventions.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class JobRun(Base):
    """A single background-job invocation tracked through its lifecycle.

    Status state machine:

        pending   → started   → success
                  → started   → failed
                  → cancelled (from pending or started)
                  → started   → retry (and back to pending or started)
    """

    __tablename__ = "oe_job_run"
    __table_args__ = (
        Index("ix_oe_job_run_kind_status", "kind", "status"),
        Index("ix_oe_job_run_tenant_id", "tenant_id"),
    )

    # ``id`` / ``created_at`` / ``updated_at`` come from Base.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        doc="Tenant scope for RLS once enabled. NULL for cross-tenant / system jobs.",
    )
    kind: Mapped[str] = mapped_column(
        String(120),
        nullable=False,
        index=True,
        doc="Logical handler key — e.g. 'cad.convert', 'eac.run'.",
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="pending",
        server_default="pending",
        index=True,
        doc="One of: pending, started, success, failed, cancelled, retry.",
    )
    progress_percent: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    payload_jsonb: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        "payload_jsonb",
        JSON,
        nullable=True,
        doc="Input payload for the handler. Frozen on submit.",
    )
    result_jsonb: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        "result_jsonb",
        JSON,
        nullable=True,
        doc="Handler return value when status='success', plus running progress_message.",
    )
    error_jsonb: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        "error_jsonb",
        JSON,
        nullable=True,
        doc="{type, message, traceback} on failure; NULL otherwise.",
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    retry_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    idempotency_key: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
        doc="Optional caller-supplied de-duplication token.",
    )
    celery_task_id: Mapped[str | None] = mapped_column(
        String(120),
        nullable=True,
        doc="Celery's own task UUID, recorded for cross-system debugging.",
    )

    def __repr__(self) -> str:
        return (
            f"<JobRun id={self.id} kind={self.kind} "
            f"status={self.status} progress={self.progress_percent}%>"
        )
