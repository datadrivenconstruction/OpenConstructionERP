"""v2.6.0 W0.1 -- create the oe_job_run table for the Celery job runner.

Backs the JobRun model in ``app/core/job_run.py``. RFC 34 §4 W0.1.

Idempotent: each schema-touching call is gated by an introspection
check so re-running this migration on an already-migrated database is
a no-op — matches the convention established by v231 and v250.

Revision ID: v260_jobs_runner
Revises: v250_dashboards_snapshot
Create Date: 2026-04-25
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v260_jobs_runner"
down_revision: Union[str, None] = "v250_dashboards_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "oe_job_run"
KIND_INDEX = "ix_oe_job_run_kind"
STATUS_INDEX = "ix_oe_job_run_status"
KIND_STATUS_INDEX = "ix_oe_job_run_kind_status"
TENANT_INDEX = "ix_oe_job_run_tenant_id"
IDEMPOTENCY_INDEX = "ix_oe_job_run_idempotency_key"


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def _has_index(table: str, index_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(ix["name"] == index_name for ix in insp.get_indexes(table))


def upgrade() -> None:
    if not _table_exists(TABLE_NAME):
        op.create_table(
            TABLE_NAME,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column("kind", sa.String(length=120), nullable=False),
            sa.Column(
                "status",
                sa.String(length=20),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "progress_percent",
                sa.Integer,
                nullable=False,
                server_default="0",
            ),
            sa.Column("payload_jsonb", sa.JSON, nullable=True),
            sa.Column("result_jsonb", sa.JSON, nullable=True),
            sa.Column("error_jsonb", sa.JSON, nullable=True),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "retry_count",
                sa.Integer,
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "idempotency_key",
                sa.String(length=255),
                nullable=True,
                unique=True,
            ),
            sa.Column("celery_task_id", sa.String(length=120), nullable=True),
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
        )

    # Indexes are created separately so we can re-run the migration on
    # a partially-built schema (e.g., a hand-edited dev DB) without
    # tripping a "table exists, index exists" race.
    if not _has_index(TABLE_NAME, KIND_INDEX):
        op.create_index(KIND_INDEX, TABLE_NAME, ["kind"])
    if not _has_index(TABLE_NAME, STATUS_INDEX):
        op.create_index(STATUS_INDEX, TABLE_NAME, ["status"])
    if not _has_index(TABLE_NAME, KIND_STATUS_INDEX):
        op.create_index(KIND_STATUS_INDEX, TABLE_NAME, ["kind", "status"])
    if not _has_index(TABLE_NAME, TENANT_INDEX):
        op.create_index(TENANT_INDEX, TABLE_NAME, ["tenant_id"])
    if not _has_index(TABLE_NAME, IDEMPOTENCY_INDEX):
        op.create_index(IDEMPOTENCY_INDEX, TABLE_NAME, ["idempotency_key"])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if TABLE_NAME in insp.get_table_names():
        existing = {ix["name"] for ix in insp.get_indexes(TABLE_NAME)}
        for idx in (
            IDEMPOTENCY_INDEX,
            TENANT_INDEX,
            KIND_STATUS_INDEX,
            STATUS_INDEX,
            KIND_INDEX,
        ):
            if idx in existing:
                op.drop_index(idx, table_name=TABLE_NAME)
        op.drop_table(TABLE_NAME)
