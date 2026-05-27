"""AI Agents — runs + steps tables (v4.0 / Slice 1).

Adds two strictly-additive tables that back the ReAct agent loop:

* ``oe_ai_agents_run`` — one row per agent invocation.
* ``oe_ai_agents_step`` — chronological steps within a run.

Idempotent — inspector-guarded so re-runs on a partially migrated DB
skip already-present tables / indexes. SQLite-safe via
``GUID() -> VARCHAR(36)`` and JSON columns stored as TEXT.

Revision ID: v40_ai_agents
Revises: v40_assembly_templates
Create Date: 2026-05-20
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v40_ai_agents"
down_revision: Union[str, Sequence[str], None] = "v40_assembly_templates"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_RUN_TABLE = "oe_ai_agents_run"
_STEP_TABLE = "oe_ai_agents_step"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _existing_index_names(
    inspector: sa.engine.reflection.Inspector,
    table: str,
) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    """Create both AI-Agents tables + supporting indexes."""
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)
    inspector = sa.inspect(bind)

    # ── oe_ai_agents_run ──────────────────────────────────────────────────
    if not _has_table(inspector, _RUN_TABLE):
        op.create_table(
            _RUN_TABLE,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column("agent_name", sa.String(100), nullable=False),
            sa.Column("project_id", guid_type, nullable=True),
            sa.Column("user_id", guid_type, nullable=False),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="running",
            ),
            sa.Column("failure_reason", sa.String(100), nullable=True),
            sa.Column(
                "user_input",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column("final_output", sa.Text(), nullable=True),
            sa.Column(
                "iterations",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "total_tokens",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("started_at", sa.String(40), nullable=True),
            sa.Column("finished_at", sa.String(40), nullable=True),
        )

        existing_ix = _existing_index_names(inspector, _RUN_TABLE)
        for ix_name, cols in (
            ("ix_oe_ai_agents_run_agent_name", ["agent_name"]),
            ("ix_oe_ai_agents_run_project_id", ["project_id"]),
            ("ix_oe_ai_agents_run_user_id", ["user_id"]),
        ):
            if ix_name not in existing_ix:
                try:
                    op.create_index(ix_name, _RUN_TABLE, cols)
                except sa.exc.OperationalError:
                    pass

    # ── oe_ai_agents_step ─────────────────────────────────────────────────
    if not _has_table(inspector, _STEP_TABLE):
        op.create_table(
            _STEP_TABLE,
            sa.Column("id", guid_type, primary_key=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
            sa.Column(
                "run_id",
                guid_type,
                sa.ForeignKey(f"{_RUN_TABLE}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "step_idx",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("role", sa.String(30), nullable=False),
            sa.Column(
                "content",
                sa.JSON(),
                nullable=False,
                server_default=sa.text("'{}'"),
            ),
            sa.Column(
                "token_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )

        existing_ix = _existing_index_names(inspector, _STEP_TABLE)
        ix_run = "ix_oe_ai_agents_step_run_id"
        if ix_run not in existing_ix:
            try:
                op.create_index(ix_run, _STEP_TABLE, ["run_id"])
            except sa.exc.OperationalError:
                pass


def downgrade() -> None:
    """Drop both AI-Agents tables."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _STEP_TABLE):
        for ix in ("ix_oe_ai_agents_step_run_id",):
            try:
                op.drop_index(ix, table_name=_STEP_TABLE)
            except sa.exc.OperationalError:
                pass
        op.drop_table(_STEP_TABLE)

    if _has_table(inspector, _RUN_TABLE):
        for ix in (
            "ix_oe_ai_agents_run_agent_name",
            "ix_oe_ai_agents_run_project_id",
            "ix_oe_ai_agents_run_user_id",
        ):
            try:
                op.drop_index(ix, table_name=_RUN_TABLE)
            except sa.exc.OperationalError:
                pass
        op.drop_table(_RUN_TABLE)
