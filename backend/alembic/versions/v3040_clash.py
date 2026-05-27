# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Clash detection — oe_clash_run + oe_clash_result tables.

Backs the geometric AABB coordination feature: a ``ClashRun`` is one
analysis over N BIM models, and each ``ClashResult`` is a clashing
element pair carrying a discipline/name snapshot so the result list
survives a source-model re-import.

Idempotent: guarded by an inspector so re-running after SQLite's
``Base.metadata.create_all`` (dev) is a no-op; Postgres prod gets the
DDL. ``id`` / ``*_id`` columns are ``String(36)`` to match the platform's
``GUID`` TypeDecorator on SQLite + PostgreSQL.

Revision ID: v3040_clash
Revises: v3039_quantity_links
Created: 2026-05-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3040_clash"
down_revision: Union[str, Sequence[str], None] = "v3039_quantity_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RUN = "oe_clash_run"
_RESULT = "oe_clash_result"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _RUN):
        op.create_table(
            _RUN,
            sa.Column("id", sa.String(length=36), primary_key=True),
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
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(length=255), nullable=False),
            sa.Column("model_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column(
                "tolerance_m",
                sa.Float(),
                nullable=False,
                server_default="0.01",
            ),
            sa.Column(
                "clearance_m",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            ),
            sa.Column(
                "mode",
                sa.String(length=32),
                nullable=False,
                server_default="cross_discipline",
            ),
            sa.Column("discipline_filter", sa.JSON(), nullable=True),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column(
                "element_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "total_clashes",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("summary", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_by", sa.String(length=64), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_clash_run_project", _RUN, ["project_id"])

    if not _has_table(inspector, _RESULT):
        op.create_table(
            _RESULT,
            sa.Column("id", sa.String(length=36), primary_key=True),
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
            sa.Column(
                "run_id",
                sa.String(length=36),
                sa.ForeignKey("oe_clash_run.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("a_element_id", sa.String(length=36), nullable=False),
            sa.Column("b_element_id", sa.String(length=36), nullable=False),
            sa.Column("a_stable_id", sa.String(length=255), nullable=False),
            sa.Column("b_stable_id", sa.String(length=255), nullable=False),
            sa.Column(
                "a_name",
                sa.String(length=500),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "b_name",
                sa.String(length=500),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "a_discipline",
                sa.String(length=64),
                nullable=False,
                server_default="Unassigned",
            ),
            sa.Column(
                "b_discipline",
                sa.String(length=64),
                nullable=False,
                server_default="Unassigned",
            ),
            sa.Column("a_model_id", sa.String(length=36), nullable=False),
            sa.Column("b_model_id", sa.String(length=36), nullable=False),
            sa.Column(
                "clash_type",
                sa.String(length=16),
                nullable=False,
                server_default="hard",
            ),
            sa.Column(
                "penetration_m",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            ),
            sa.Column(
                "distance_m",
                sa.Float(),
                nullable=False,
                server_default="0.0",
            ),
            sa.Column("cx", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("cy", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column("cz", sa.Float(), nullable=False, server_default="0.0"),
            sa.Column(
                "status",
                sa.String(length=16),
                nullable=False,
                server_default="new",
            ),
            sa.Column("assigned_to", sa.String(length=255), nullable=True),
            sa.Column("bcf_topic_guid", sa.String(length=36), nullable=True),
        )
        op.create_index("ix_clash_result_run", _RESULT, ["run_id"])
        op.create_index("ix_clash_result_run_status", _RESULT, ["run_id", "status"])
        op.create_index(
            "ix_clash_result_run_disc",
            _RESULT,
            ["run_id", "a_discipline", "b_discipline"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_table(inspector, _RESULT):
        op.drop_table(_RESULT)
    if _has_table(inspector, _RUN):
        op.drop_table(_RUN)
