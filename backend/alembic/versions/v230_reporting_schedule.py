"""v2.3.0 -- add schedule fields to oe_reporting_template.

Six new columns let the Celery-Beat worker pick up due report templates
and email the rendered output. All nullable / default so backfill is a
no-op for pre-existing templates.

* ``schedule_cron`` — 5-field POSIX cron expression ("0 9 * * 1").
* ``recipients`` — JSON list of email addresses or user ids.
* ``is_scheduled`` — Boolean (indexed) so the worker can skip paused
  templates without scanning the cron column.
* ``last_run_at`` / ``next_run_at`` — ISO-8601 strings; indexed on
  next_run_at so due-query costs O(log n).
* ``project_id_scope`` — optional GUID; ``NULL`` = portfolio report.

Idempotent — checks live schema and adds only missing columns.

Revision ID: v230_reporting_schedule
Revises: v230_bim_element_asset_info
Create Date: 2026-04-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "v230_reporting_schedule"
down_revision: Union[str, None] = "v230_bim_element_asset_info"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "oe_reporting_template"
SCHEDULED_INDEX = "ix_reporting_template_scheduled"
NEXT_RUN_INDEX = "ix_reporting_template_next_run"


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def _has_index(table: str, index_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(ix["name"] == index_name for ix in insp.get_indexes(table))


def upgrade() -> None:
    if not _table_exists(TABLE_NAME):
        return

    if not _has_column(TABLE_NAME, "schedule_cron"):
        op.add_column(
            TABLE_NAME,
            sa.Column("schedule_cron", sa.String(length=100), nullable=True),
        )
    if not _has_column(TABLE_NAME, "recipients"):
        op.add_column(
            TABLE_NAME,
            sa.Column(
                "recipients",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )
    if not _has_column(TABLE_NAME, "is_scheduled"):
        op.add_column(
            TABLE_NAME,
            sa.Column(
                "is_scheduled",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
        )
    if not _has_column(TABLE_NAME, "last_run_at"):
        op.add_column(
            TABLE_NAME,
            sa.Column("last_run_at", sa.String(length=32), nullable=True),
        )
    if not _has_column(TABLE_NAME, "next_run_at"):
        op.add_column(
            TABLE_NAME,
            sa.Column("next_run_at", sa.String(length=32), nullable=True),
        )
    if not _has_column(TABLE_NAME, "project_id_scope"):
        op.add_column(
            TABLE_NAME,
            sa.Column(
                "project_id_scope",
                sa.CHAR(length=32),  # GUID type persists as 32-char hex on SQLite
                nullable=True,
            ),
        )

    if not _has_index(TABLE_NAME, SCHEDULED_INDEX):
        op.create_index(SCHEDULED_INDEX, TABLE_NAME, ["is_scheduled"])
    if not _has_index(TABLE_NAME, NEXT_RUN_INDEX):
        op.create_index(NEXT_RUN_INDEX, TABLE_NAME, ["next_run_at"])


def downgrade() -> None:
    if _has_index(TABLE_NAME, NEXT_RUN_INDEX):
        op.drop_index(NEXT_RUN_INDEX, table_name=TABLE_NAME)
    if _has_index(TABLE_NAME, SCHEDULED_INDEX):
        op.drop_index(SCHEDULED_INDEX, table_name=TABLE_NAME)
    for col in (
        "project_id_scope",
        "next_run_at",
        "last_run_at",
        "is_scheduled",
        "recipients",
        "schedule_cron",
    ):
        if _has_column(TABLE_NAME, col):
            with op.batch_alter_table(TABLE_NAME) as batch_op:
                batch_op.drop_column(col)
