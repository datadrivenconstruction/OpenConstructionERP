# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Work Requests initial schema.

Creates the seven ``oe_work_requests_*`` tables. Idempotent and
inspector-guarded so a re-run on a partially-migrated database is safe.

Fresh installs get these tables from the startup ``create_all``; this
file is what a migration-managed deployment needs. Move it into
``backend/alembic/versions/`` and set ``down_revision`` to the current
head before running ``alembic upgrade head``.

Revision ID: oe_work_requests_v0001_initial
Revises: <FILL_IN_CURRENT_HEAD>
Create Date: 2026-09-03
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "oe_work_requests_v0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_DEPARTMENT = "oe_work_requests_department"
_REQUEST = "oe_work_requests_request"
_HOURS = "oe_work_requests_request_hours"
_COMMENT = "oe_work_requests_comment"
_ALLOC = "oe_work_requests_planner_alloc"
_CAPACITY = "oe_work_requests_planner_capacity"
_COUNTER = "oe_work_requests_counter"


def _has(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # GUID is VARCHAR(36) on every dialect (see app.database.GUID).
    guid = sa.String(36)

    if not _has(inspector, _DEPARTMENT):
        op.create_table(
            _DEPARTMENT,
            sa.Column("id", guid, primary_key=True),
            sa.Column("key", sa.String(40), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("prefix", sa.String(12), nullable=False),
            sa.Column("colour", sa.String(30), nullable=False, server_default="slate"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("active", sa.Boolean(), nullable=False, server_default="true"),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("lead_user_id", sa.String(36), nullable=True),
            sa.Column("member_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("hourly_rate", sa.String(20), nullable=True),
            sa.Column("stages", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("request_types", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("target_days", sa.Integer(), nullable=True),
            *_timestamps(),
            sa.UniqueConstraint("key", name="uq_oe_work_requests_department_key"),
            sa.UniqueConstraint("prefix", name="uq_oe_work_requests_department_prefix"),
        )

    if not _has(inspector, _REQUEST):
        op.create_table(
            _REQUEST,
            sa.Column("id", guid, primary_key=True),
            sa.Column("project_id", guid, sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False),
            sa.Column("department", sa.String(40), nullable=False),
            sa.Column("request_type", sa.String(60), nullable=False, server_default=""),
            sa.Column("request_types", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("reference", sa.String(40), nullable=False),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="submitted"),
            sa.Column("stage", sa.String(60), nullable=True),
            sa.Column("stage_history", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("raised_by_id", sa.String(36), nullable=False, server_default=""),
            sa.Column("raised_by_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("assignee_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("responsible_user_id", sa.String(36), nullable=True),
            sa.Column("cost_centres", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("estimated_hours", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("quoted_hours", sa.Float(), nullable=True),
            sa.Column("hours_to_complete", sa.Float(), nullable=True),
            sa.Column("info_required_by", sa.String(10), nullable=True),
            sa.Column("due_date", sa.String(10), nullable=True),
            sa.Column("scheduled_start", sa.String(10), nullable=True),
            sa.Column("scheduled_end", sa.String(10), nullable=True),
            sa.Column("delivered_at", sa.String(10), nullable=True),
            sa.Column("tested_at", sa.String(10), nullable=True),
            sa.Column("priority", sa.String(10), nullable=False, server_default="normal"),
            sa.Column("links", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("fields", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("planner_uploaded", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("ball_in_court", sa.String(12), nullable=False, server_default="department"),
            sa.Column("needs_info", sa.Text(), nullable=True),
            sa.Column("depends_on_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("parent_id", guid, sa.ForeignKey(f"{_REQUEST}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("attachments", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("notified", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("checklist_state", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("is_template", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("schedule_activity_id", guid, nullable=True),
            sa.Column("boq_position_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("accepted_at", sa.String(10), nullable=True),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            *_timestamps(),
            # The series is per department and global across jobs; the
            # counter is read under a row lock and this is the backstop.
            sa.UniqueConstraint("reference", name="uq_oe_work_requests_request_reference"),
        )
        for col in (
            "project_id",
            "department",
            "status",
            "stage",
            "raised_by_id",
            "responsible_user_id",
            "due_date",
            "parent_id",
            "is_template",
        ):
            op.create_index(f"ix_{_REQUEST}_{col}", _REQUEST, [col])
        op.create_index("ix_work_requests_request_project_dept", _REQUEST, ["project_id", "department"])
        op.create_index("ix_work_requests_request_dept_status", _REQUEST, ["department", "status"])

    if not _has(inspector, _HOURS):
        op.create_table(
            _HOURS,
            sa.Column("id", guid, primary_key=True),
            sa.Column("request_id", guid, sa.ForeignKey(f"{_REQUEST}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("user_id", sa.String(36), nullable=False, server_default=""),
            sa.Column("user_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("day", sa.String(10), nullable=False),
            sa.Column("hours", sa.Float(), nullable=False, server_default="0"),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            *_timestamps(),
        )
        op.create_index(f"ix_{_HOURS}_request_id", _HOURS, ["request_id"])
        op.create_index(f"ix_{_HOURS}_user_id", _HOURS, ["user_id"])
        op.create_index("ix_work_requests_hours_request_day", _HOURS, ["request_id", "day"])

    if not _has(inspector, _COMMENT):
        op.create_table(
            _COMMENT,
            sa.Column("id", guid, primary_key=True),
            sa.Column("request_id", guid, sa.ForeignKey(f"{_REQUEST}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("author_id", sa.String(36), nullable=False, server_default=""),
            sa.Column("author_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("detail", sa.Text(), nullable=False, server_default=""),
            sa.Column("mention_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("kind", sa.String(20), nullable=False, server_default="comment"),
            *_timestamps(),
        )
        op.create_index(f"ix_{_COMMENT}_request_id", _COMMENT, ["request_id"])
        op.create_index("ix_work_requests_comment_request_created", _COMMENT, ["request_id", "created_at"])

    if not _has(inspector, _ALLOC):
        op.create_table(
            _ALLOC,
            sa.Column("id", guid, primary_key=True),
            sa.Column("request_id", guid, sa.ForeignKey(f"{_REQUEST}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("day", sa.String(10), nullable=False),
            sa.Column("people", sa.Float(), nullable=False, server_default="0"),
            *_timestamps(),
            sa.UniqueConstraint("request_id", "day", name="uq_oe_work_requests_planner_alloc_request_day"),
        )
        op.create_index(f"ix_{_ALLOC}_request_id", _ALLOC, ["request_id"])
        op.create_index(f"ix_{_ALLOC}_day", _ALLOC, ["day"])

    if not _has(inspector, _CAPACITY):
        op.create_table(
            _CAPACITY,
            sa.Column("id", guid, primary_key=True),
            sa.Column("department", sa.String(40), nullable=False),
            sa.Column("day", sa.String(10), nullable=False),
            sa.Column("available", sa.Float(), nullable=False, server_default="0"),
            *_timestamps(),
            sa.UniqueConstraint("department", "day", name="uq_oe_work_requests_planner_capacity_department_day"),
        )
        op.create_index(f"ix_{_CAPACITY}_department", _CAPACITY, ["department"])

    if not _has(inspector, _COUNTER):
        op.create_table(
            _COUNTER,
            sa.Column("id", guid, primary_key=True),
            sa.Column("prefix", sa.String(12), nullable=False),
            sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
            *_timestamps(),
            sa.UniqueConstraint("prefix", name="uq_oe_work_requests_counter_prefix"),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Children first: they carry the FK onto requests.
    for name in (_ALLOC, _COMMENT, _HOURS, _CAPACITY, _COUNTER, _REQUEST, _DEPARTMENT):
        if _has(inspector, name):
            op.drop_table(name)
