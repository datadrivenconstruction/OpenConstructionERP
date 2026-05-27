# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3-P10 — match search log analytics table.

Per MAPPING_PROCESS.md v3 §6.5 the ranker logs one row per Qdrant call
into ``oe_match_elements_search_log`` so operators can audit:

    * relax-tier distribution (how often the §5.2 ladder kicks in),
    * top-score vs hard-filter-count for §6.4 confidence calibration,
    * latency p95 with / without BGE rerank,
    * catalogue gap detection (low ``top_score`` clustered on the same
      ``catalog_id`` flags vectorisation bugs).

Migration is idempotent — re-applying on an already-migrated DB skips
the table and indexes already present.

Revision ID: v2934_match_search_log
Revises: v2933_match_elements_resume
Create Date: 2026-05-09
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v2934_match_search_log"
down_revision: Union[str, Sequence[str], None] = "v2933_match_elements_resume"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_match_elements_search_log"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, index: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    if not _has_table(inspector, _TABLE):
        op.create_table(
            _TABLE,
            # Base mixin columns mirror oe_match_elements_session.
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
            sa.Column("project_id", guid_type, nullable=False),
            sa.Column("session_id", guid_type, nullable=True),
            sa.Column("group_id", guid_type, nullable=True),
            sa.Column("catalog_id", sa.String(64), nullable=True),
            sa.Column("collection_name", sa.String(64), nullable=True),
            sa.Column("core_query", sa.String(2000), nullable=True),
            sa.Column("hard_filters", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("soft_boosts", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("hits_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("relax_tier_used", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("top_score", sa.Float(), nullable=True),
            sa.Column("top_confidence_band", sa.String(16), nullable=True),
            sa.Column("bge_rerank_used", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("llm_rerank_used", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("took_ms", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(32), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.ForeignKeyConstraint(
                ["project_id"],
                ["oe_projects_project.id"],
                ondelete="CASCADE",
            ),
            sa.ForeignKeyConstraint(
                ["session_id"],
                ["oe_match_elements_session.id"],
                ondelete="SET NULL",
            ),
            sa.ForeignKeyConstraint(
                ["group_id"],
                ["oe_match_elements_group.id"],
                ondelete="SET NULL",
            ),
        )

    # Inspector cache is stale after CREATE TABLE — re-inspect.
    inspector = sa.inspect(bind)

    indexes = [
        ("ix_match_search_log_project_time", ["project_id", "created_at"]),
        ("ix_match_search_log_catalog_time", ["catalog_id", "created_at"]),
        ("ix_match_search_log_session", ["session_id"]),
        ("ix_match_search_log_tier", ["relax_tier_used"]),
        ("ix_oe_match_elements_search_log_project_id", ["project_id"]),
    ]
    for name, cols in indexes:
        if not _has_index(inspector, _TABLE, name):
            op.create_index(name, _TABLE, cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_table(inspector, _TABLE):
        for name in (
            "ix_match_search_log_project_time",
            "ix_match_search_log_catalog_time",
            "ix_match_search_log_session",
            "ix_match_search_log_tier",
            "ix_oe_match_elements_search_log_project_id",
        ):
            if _has_index(inspector, _TABLE, name):
                op.drop_index(name, table_name=_TABLE)
        op.drop_table(_TABLE)
