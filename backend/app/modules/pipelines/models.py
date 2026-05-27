# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""‌⁠‍Pipeline Builder ORM models.

Three tables, following the match-elements conventions (§3.4):

    oe_pipeline             — the saved graph: ``{nodes, edges}`` JSON +
                              policy + version + publish flag. Versioned
                              like ``MatchPromptTemplate`` (system vs user,
                              fork-to-edit comes in a later phase).
    oe_pipeline_run         — a thin pointer to the owning ``oe_job_run``
                              plus a frozen graph snapshot + trigger
                              context, for fast project-scoped listing.
    oe_pipeline_node_state  — a near-clone of ``MatchStageState``: one row
                              per (run, node), ``status`` advancing
                              pending → running → done | error, with small
                              ``inputs`` / ``output`` envelopes (never the
                              big payload — §3.2 hard rule 1).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Pipeline(Base):
    """‌⁠‍A saved, versioned node-graph automation.

    ``graph`` is the editor's source of truth: ``{"nodes": [...],
    "edges": [...]}``. ``policy`` holds run-as / scheduling / retry knobs
    (a flexible bag so future phases extend it without a migration). A
    pipeline that fails the structural ``pipeline`` validation rule cannot
    be published, and only a published pipeline can be triggered.
    """

    __tablename__ = "oe_pipeline"
    __table_args__ = (
        Index("ix_oe_pipeline_project", "project_id"),
        Index("ix_oe_pipeline_tenant", "tenant_id"),
        Index("ix_oe_pipeline_published", "is_published"),
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Nullable: a pipeline can be project-scoped or a tenant/global template.
    project_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # The editor graph: {"nodes":[{id,type,params,position}], "edges":[...]}.
    graph: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    # Run-as / schedule / retry / concurrency knobs. Flexible by design.
    policy: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<Pipeline {self.name} v{self.version} published={self.is_published}>"


class PipelineRun(Base):
    """‌⁠‍One execution of a pipeline — a thin pointer to an ``oe_job_run``.

    The heavy lifecycle (submit / progress / retry / cancel / idempotency)
    lives on the ``JobRun`` row identified by ``job_run_id``. This table
    only adds the frozen ``graph_snapshot`` (so a later graph edit can't
    rewrite history) and the ``trigger`` context, plus a project-scoped
    index for fast run listings.
    """

    __tablename__ = "oe_pipeline_run"
    __table_args__ = (
        Index("ix_oe_pipeline_run_pipeline", "pipeline_id"),
        Index("ix_oe_pipeline_run_job", "job_run_id"),
        Index("ix_oe_pipeline_run_project", "project_id"),
        Index("ix_oe_pipeline_run_tenant", "tenant_id"),
    )

    pipeline_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_pipeline.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Pointer into oe_job_run — the durable run lifecycle lives there.
    job_run_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # Frozen copy of pipeline.graph at submit time (immutable history).
    graph_snapshot: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    # How this run was started: {"type":"manual","actor_id":...} etc.
    trigger: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<PipelineRun pipeline={self.pipeline_id} job={self.job_run_id}>"


class PipelineNodeState(Base):
    """Per-run × per-node runtime state — a near-clone of ``MatchStageState``.

    One row per ``(run_id, node_id)``. ``status`` advances
    pending → running → done | error (plus skipped / stale / paused for
    re-runs and Phase-2 approval gates). ``inputs`` captures the node's
    params + which upstream nodes fed it; ``output`` is a SMALL envelope
    (counts, samples, IDs) — the full payload always stays in its owning
    table, which is what keeps the SQLite / 2 GB-RAM target healthy.
    """

    __tablename__ = "oe_pipeline_node_state"
    __table_args__ = (
        UniqueConstraint("run_id", "node_id", name="uq_oe_pipeline_node_state_run_node"),
        Index("ix_oe_pipeline_node_state_run", "run_id"),
        Index("ix_oe_pipeline_node_state_status", "status"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_pipeline_run.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    node_id: Mapped[str] = mapped_column(String(128), nullable=False)
    node_type: Mapped[str] = mapped_column(String(64), nullable=False)
    # pending | running | done | error | skipped | stale | paused
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending", server_default="pending")
    inputs: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    output: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict, server_default="{}"
    )
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    took_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def __repr__(self) -> str:
        return f"<PipelineNodeState run={self.run_id} node={self.node_id} status={self.status}>"
