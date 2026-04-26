"""v2.5.0 T01 -- create dashboards snapshot + source_file tables.

Two new tables land together because the snapshot row is meaningless
without its source-file descriptors, and both are created in a single
service call (``SnapshotService.create``). Idempotent: checks live
schema before adding anything.

Revision ID: v250_dashboards_snapshot
Revises: v231_contact_tenant_id
Create Date: 2026-04-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v250_dashboards_snapshot"
down_revision: Union[str, None] = "v231_contact_tenant_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SNAPSHOT_TABLE = "oe_dashboards_snapshot"
SOURCE_FILE_TABLE = "oe_dashboards_source_file"
SNAPSHOT_LABEL_UQ = "uq_oe_dashboards_snapshot_project_label"
SNAPSHOT_PROJECT_IX = "ix_oe_dashboards_snapshot_project_id"
SNAPSHOT_TENANT_IX = "ix_oe_dashboards_snapshot_tenant_id"
SOURCE_FILE_SNAPSHOT_IX = "ix_oe_dashboards_source_file_snapshot_id"


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def upgrade() -> None:
    if not _table_exists(SNAPSHOT_TABLE):
        op.create_table(
            SNAPSHOT_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "project_id", sa.String(length=36), nullable=False,
            ),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column("label", sa.String(length=200), nullable=False),
            sa.Column("parquet_dir", sa.String(length=500), nullable=False),
            sa.Column("total_entities", sa.Integer, nullable=False, server_default="0"),
            sa.Column("total_categories", sa.Integer, nullable=False, server_default="0"),
            sa.Column("summary_stats", sa.JSON, nullable=False, server_default="{}"),
            sa.Column("source_files_json", sa.JSON, nullable=False, server_default="[]"),
            sa.Column("parent_snapshot_id", sa.String(length=36), nullable=True),
            sa.Column("created_by_user_id", sa.String(length=36), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["project_id"], ["oe_projects_project.id"], ondelete="CASCADE",
            ),
            sa.UniqueConstraint(
                "project_id", "label", name=SNAPSHOT_LABEL_UQ,
            ),
        )
        op.create_index(SNAPSHOT_PROJECT_IX, SNAPSHOT_TABLE, ["project_id"])
        op.create_index(SNAPSHOT_TENANT_IX, SNAPSHOT_TABLE, ["tenant_id"])

    if not _table_exists(SOURCE_FILE_TABLE):
        op.create_table(
            SOURCE_FILE_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("snapshot_id", sa.String(length=36), nullable=False),
            sa.Column("original_name", sa.String(length=500), nullable=False),
            sa.Column("format", sa.String(length=20), nullable=False),
            sa.Column("discipline", sa.String(length=100), nullable=True),
            sa.Column("entity_count", sa.Integer, nullable=False, server_default="0"),
            sa.Column("bytes_size", sa.Integer, nullable=False, server_default="0"),
            sa.Column("converter_notes", sa.JSON, nullable=False, server_default="{}"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("CURRENT_TIMESTAMP"),
            ),
            sa.ForeignKeyConstraint(
                ["snapshot_id"], [f"{SNAPSHOT_TABLE}.id"], ondelete="CASCADE",
            ),
        )
        op.create_index(
            SOURCE_FILE_SNAPSHOT_IX, SOURCE_FILE_TABLE, ["snapshot_id"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if SOURCE_FILE_TABLE in insp.get_table_names():
        existing = {ix["name"] for ix in insp.get_indexes(SOURCE_FILE_TABLE)}
        if SOURCE_FILE_SNAPSHOT_IX in existing:
            op.drop_index(SOURCE_FILE_SNAPSHOT_IX, table_name=SOURCE_FILE_TABLE)
        op.drop_table(SOURCE_FILE_TABLE)

    if SNAPSHOT_TABLE in insp.get_table_names():
        existing = {ix["name"] for ix in insp.get_indexes(SNAPSHOT_TABLE)}
        if SNAPSHOT_PROJECT_IX in existing:
            op.drop_index(SNAPSHOT_PROJECT_IX, table_name=SNAPSHOT_TABLE)
        if SNAPSHOT_TENANT_IX in existing:
            op.drop_index(SNAPSHOT_TENANT_IX, table_name=SNAPSHOT_TABLE)
        op.drop_table(SNAPSHOT_TABLE)
