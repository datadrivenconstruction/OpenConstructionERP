# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pipeline Builder Phase 1 — pipeline / run / node-state tables.

Adds the three tables backing the ``oe_pipelines`` module (design §3.4):

* ``oe_pipeline``             — the saved, versioned node graph
  (``{nodes, edges}`` JSON) + policy + publish flag.
* ``oe_pipeline_run``         — a thin pointer to ``oe_job_run`` plus a
  frozen graph snapshot + trigger context (the durable run lifecycle
  lives on the JobRun row).
* ``oe_pipeline_node_state``  — one row per (run, node); a near-clone of
  ``oe_match_elements_stage`` (status pending → running → done | error,
  small inputs/output envelopes).

Idempotent: each table is guarded by an inspector so re-running after
SQLite's ``Base.metadata.create_all`` (dev) is a no-op; Postgres prod
gets the DDL. All ``id`` / ``*_id`` columns are ``String(36)`` to match
the platform's ``GUID`` TypeDecorator on SQLite + PostgreSQL.

Revision ID: v3037_pipelines
Revises: v3036_linked_positions
Created: 2026-05-17
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3037_pipelines"
down_revision: Union[str, Sequence[str], None] = "v3036_linked_positions"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _ts_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


def upgrade() -> None:
    """Create the three pipeline tables (idempotent)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── 1. oe_pipeline ───────────────────────────────────────────────
    if not _has_table(inspector, "oe_pipeline"):
        op.create_table(
            "oe_pipeline",
            sa.Column("id", sa.String(length=36), primary_key=True),
            *_ts_columns(),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column("graph", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("policy", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column(
                "is_published",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0"),
            ),
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("created_by", sa.String(length=36), nullable=True),
        )
        op.create_index("ix_oe_pipeline_project", "oe_pipeline", ["project_id"])
        op.create_index("ix_oe_pipeline_tenant", "oe_pipeline", ["tenant_id"])
        op.create_index("ix_oe_pipeline_published", "oe_pipeline", ["is_published"])

    # ── 2. oe_pipeline_run ───────────────────────────────────────────
    if not _has_table(inspector, "oe_pipeline_run"):
        op.create_table(
            "oe_pipeline_run",
            sa.Column("id", sa.String(length=36), primary_key=True),
            *_ts_columns(),
            sa.Column(
                "pipeline_id",
                sa.String(length=36),
                sa.ForeignKey("oe_pipeline.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("job_run_id", sa.String(length=36), nullable=True),
            sa.Column(
                "graph_snapshot",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("trigger", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("project_id", sa.String(length=36), nullable=True),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column("created_by", sa.String(length=36), nullable=True),
        )
        op.create_index(
            "ix_oe_pipeline_run_pipeline",
            "oe_pipeline_run",
            ["pipeline_id"],
        )
        op.create_index("ix_oe_pipeline_run_job", "oe_pipeline_run", ["job_run_id"])
        op.create_index(
            "ix_oe_pipeline_run_project",
            "oe_pipeline_run",
            ["project_id"],
        )
        op.create_index(
            "ix_oe_pipeline_run_tenant",
            "oe_pipeline_run",
            ["tenant_id"],
        )

    # ── 3. oe_pipeline_node_state ────────────────────────────────────
    if not _has_table(inspector, "oe_pipeline_node_state"):
        op.create_table(
            "oe_pipeline_node_state",
            sa.Column("id", sa.String(length=36), primary_key=True),
            *_ts_columns(),
            sa.Column(
                "run_id",
                sa.String(length=36),
                sa.ForeignKey("oe_pipeline_run.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("node_id", sa.String(length=128), nullable=False),
            sa.Column("node_type", sa.String(length=64), nullable=False),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("inputs", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("output", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("took_ms", sa.Integer(), nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
            sa.UniqueConstraint(
                "run_id",
                "node_id",
                name="uq_oe_pipeline_node_state_run_node",
            ),
        )
        op.create_index(
            "ix_oe_pipeline_node_state_run",
            "oe_pipeline_node_state",
            ["run_id"],
        )
        op.create_index(
            "ix_oe_pipeline_node_state_status",
            "oe_pipeline_node_state",
            ["status"],
        )


def downgrade() -> None:
    """Drop the three pipeline tables (reverse FK order)."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in (
        "oe_pipeline_node_state",
        "oe_pipeline_run",
        "oe_pipeline",
    ):
        if _has_table(inspector, table):
            op.drop_table(table)
