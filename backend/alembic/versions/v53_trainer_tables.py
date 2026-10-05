# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""trainer - the Academy course trainer tables.

Seven new tables for module ``oe_trainer`` (models in
``app/modules/trainer/models.py``): ``oe_trainer_course``, ``oe_trainer_offer``,
``oe_trainer_enrolment``, ``oe_trainer_task_state``, ``oe_trainer_answer``,
``oe_trainer_attempt`` and ``oe_trainer_webhook_event``. Nothing is backfilled;
an install that never turns ``OE_ACADEMY_MODE`` on keeps them empty.

This one does NOT need running by hand. It adds tables and nothing else, and
``Base.metadata.create_all`` creates every table the models declare that the
database does not have yet, so a running install that boots the new code gets
them from the models without an upgrade. The revision exists so that an install
that walks the chain with ``alembic upgrade head`` ends up with exactly the same
tables, constraints and indexes: the names below are the ones the metadata
naming convention in ``app.database`` produces, and every multi-column
constraint carries the explicit name the model gives it. The models also
declare the indexes ``app.core.pg_optimizations`` adds on ``create_all`` (an
index per unindexed foreign key, and the ``project_id`` composites), so this
revision builds those too and the two paths cannot drift.

Inspector-guarded per table, so a re-run on a database that already has a
table, or a downgrade on one that never got it, changes nothing. Downgrade
drops children before ``oe_trainer_course``, which the enrolment foreign key
restricts.

Revision ID: v53_trainer_tables
Revises: v52_reporting_report_published
Create Date: 2026-10-05
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v53_trainer_tables"
down_revision: Union[str, Sequence[str], None] = "v52_reporting_report_published"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_GUID = sa.String(36)


def _base_columns() -> list[sa.Column]:
    """``id``, ``created_at`` and ``updated_at``, as ``app.database.Base`` builds them."""
    return [
        sa.Column("id", _GUID, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _create_course() -> None:
    table = "oe_trainer_course"
    op.create_table(
        table,
        *_base_columns(),
        sa.Column("course_key", sa.String(80), nullable=False),
        sa.Column("version", sa.String(20), nullable=False),
        sa.Column("country", sa.String(2), nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("source_file", sa.String(255), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("spec", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("validation_report", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        sa.UniqueConstraint("course_key", "version", name="uq_oe_trainer_course_course_key_version"),
    )
    op.create_index(f"ix_{table}_country", table, ["country"])


def _create_offer() -> None:
    table = "oe_trainer_offer"
    op.create_table(
        table,
        *_base_columns(),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("product_ref", sa.String(128), nullable=False),
        sa.Column("course_key", sa.String(80), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        sa.UniqueConstraint(
            "provider",
            "product_ref",
            "course_key",
            name="uq_oe_trainer_offer_provider_product_ref_course_key",
        ),
    )


def _create_enrolment() -> None:
    table = "oe_trainer_enrolment"
    op.create_table(
        table,
        *_base_columns(),
        sa.Column("user_id", _GUID, nullable=False),
        sa.Column("course_id", _GUID, nullable=False),
        sa.Column("course_sha256", sa.String(64), nullable=False),
        sa.Column("project_id", _GUID, nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("seeded_refs", sa.JSON(), server_default="{}", nullable=False),
        sa.Column("current_task_n", sa.Integer(), nullable=False),
        sa.Column("source", sa.String(16), nullable=False),
        sa.Column("order_ref", sa.String(128), nullable=True),
        sa.Column("stale_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", sa.JSON(), server_default="{}", nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["oe_users_user.id"],
            name=f"fk_{table}_user_id_oe_users_user",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["course_id"],
            ["oe_trainer_course.id"],
            name=f"fk_{table}_course_id_oe_trainer_course",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["oe_projects_project.id"],
            name=f"fk_{table}_project_id_oe_projects_project",
            ondelete="SET NULL",
        ),
        sa.UniqueConstraint("user_id", "course_id", name="uq_oe_trainer_enrolment_user_id_course_id"),
    )
    op.create_index(f"ix_{table}_user_id", table, ["user_id"])
    op.create_index(f"ix_{table}_course_id", table, ["course_id"])
    op.create_index(f"ix_{table}_project_id", table, ["project_id"])
    op.create_index(f"ix_{table}_status", table, ["status"])
    op.create_index(f"ix_{table}_stale_since", table, ["stale_since"])
    op.create_index("ix_oe_trainer_enrolment_project_id_status", table, ["project_id", "status"])
    op.create_index("ix_oe_trainer_enrolment_project_id_created_at", table, ["project_id", "created_at"])


def _enrolment_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["enrolment_id"],
        ["oe_trainer_enrolment.id"],
        name=f"fk_{table}_enrolment_id_oe_trainer_enrolment",
        ondelete="CASCADE",
    )


def _create_task_state() -> None:
    table = "oe_trainer_task_state"
    op.create_table(
        table,
        *_base_columns(),
        sa.Column("enrolment_id", _GUID, nullable=False),
        sa.Column("task_id", sa.String(16), nullable=False),
        sa.Column("task_n", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(12), nullable=False),
        sa.Column("unlocked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("passed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("unlock_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("seed_status", sa.String(12), nullable=False),
        sa.Column("seed_error", sa.Text(), nullable=True),
        sa.Column("attempts_count", sa.Integer(), nullable=False),
        sa.Column("best_passed_items", sa.Integer(), nullable=False),
        sa.Column("total_items", sa.Integer(), nullable=False),
        sa.Column("hints_revealed", sa.Integer(), nullable=False),
        sa.Column("answers_revision", sa.Integer(), nullable=False),
        sa.Column("last_attempt_id", _GUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        _enrolment_fk(table),
        sa.UniqueConstraint("enrolment_id", "task_id", name="uq_oe_trainer_task_state_enrolment_id_task_id"),
    )
    op.create_index("ix_oe_trainer_task_state_enrolment_id_task_n", table, ["enrolment_id", "task_n"])


def _create_answer() -> None:
    table = "oe_trainer_answer"
    op.create_table(
        table,
        *_base_columns(),
        sa.Column("enrolment_id", _GUID, nullable=False),
        sa.Column("task_id", sa.String(16), nullable=False),
        sa.Column("answer_name", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("value_text", sa.String(64), nullable=True),
        sa.Column("option_index", sa.Integer(), nullable=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        _enrolment_fk(table),
        sa.UniqueConstraint(
            "enrolment_id",
            "task_id",
            "answer_name",
            name="uq_oe_trainer_answer_enrolment_id_task_id_answer_name",
        ),
    )
    op.create_index(f"ix_{table}_enrolment_id", table, ["enrolment_id"])


def _create_attempt() -> None:
    table = "oe_trainer_attempt"
    op.create_table(
        table,
        *_base_columns(),
        sa.Column("enrolment_id", _GUID, nullable=False),
        sa.Column("task_id", sa.String(16), nullable=False),
        sa.Column("client_attempt_id", _GUID, nullable=True),
        sa.Column("trigger", sa.String(12), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("graded_items", sa.Integer(), nullable=False),
        sa.Column("passed_items", sa.Integer(), nullable=False),
        sa.Column("result", sa.JSON(), server_default="[]", nullable=False),
        sa.Column("spec_sha256", sa.String(64), nullable=False),
        sa.Column("engine_version", sa.String(16), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        _enrolment_fk(table),
        sa.UniqueConstraint(
            "enrolment_id",
            "client_attempt_id",
            name="uq_oe_trainer_attempt_enrolment_id_client_attempt_id",
        ),
    )
    op.create_index(
        "ix_oe_trainer_attempt_enrolment_id_task_id_created_at",
        table,
        ["enrolment_id", "task_id", "created_at"],
    )


def _create_webhook_event() -> None:
    table = "oe_trainer_webhook_event"
    op.create_table(
        table,
        *_base_columns(),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("event_id", sa.String(128), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("signature_ok", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("email", sa.String(255), nullable=True),
        sa.Column("product_ref", sa.String(128), nullable=True),
        sa.Column("order_ref", sa.String(128), nullable=True),
        sa.Column("payload_sha256", sa.String(64), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("user_id", _GUID, nullable=True),
        sa.Column("enrolment_id", _GUID, nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=f"pk_{table}"),
        sa.UniqueConstraint("provider", "event_id", name="uq_oe_trainer_webhook_event_provider_event_id"),
    )


#: Parents before children. Downgrade walks it backwards.
_TABLES: tuple[tuple[str, Callable[[], None]], ...] = (
    ("oe_trainer_course", _create_course),
    ("oe_trainer_offer", _create_offer),
    ("oe_trainer_enrolment", _create_enrolment),
    ("oe_trainer_task_state", _create_task_state),
    ("oe_trainer_answer", _create_answer),
    ("oe_trainer_attempt", _create_attempt),
    ("oe_trainer_webhook_event", _create_webhook_event),
)


def upgrade() -> None:
    """Create each trainer table the database does not have yet."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table, create in _TABLES:
        if table not in existing:
            create()


def downgrade() -> None:
    """Drop the trainer tables, children first. Every enrolment and attempt is lost."""
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table, _create in reversed(_TABLES):
        if table in existing:
            op.drop_table(table)
