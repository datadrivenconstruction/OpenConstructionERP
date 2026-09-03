# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Register Workflow initial schema.

Creates ``oe_register_workflow_item`` and ``oe_register_workflow_step``.
Idempotent and inspector-guarded so a re-run on a partially-migrated
database is safe; SQLite-friendly (GUID ⇒ VARCHAR(36)).

Fresh installs get these tables from the startup ``create_all``; this
file is what a migration-managed deployment needs. Move it into
``backend/alembic/versions/`` and set ``down_revision`` to the current
head before running ``alembic upgrade head``.

Revision ID: oe_register_workflow_v0001_initial
Revises: <FILL_IN_CURRENT_HEAD>
Create Date: 2026-08-18
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "oe_register_workflow_v0001_initial"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ITEM = "oe_register_workflow_item"
_STEP = "oe_register_workflow_step"


def _has(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    if not _has(inspector, _ITEM):
        op.create_table(
            _ITEM,
            sa.Column("id", guid, primary_key=True),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(20), nullable=False),
            sa.Column("reference", sa.String(40), nullable=False),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("status", sa.String(20), nullable=False, server_default="open"),
            sa.Column("due_date", sa.String(20), nullable=True),
            sa.Column("fields", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("recipient_contact_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("raised_from_id", sa.String(36), nullable=True),
            sa.Column("linked_entity_type", sa.String(40), nullable=True),
            sa.Column("linked_entity_id", sa.String(36), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            # The reference generator takes MAX+1, which races under
            # concurrent raises; this constraint turns the loser into an
            # IntegrityError the service retries instead of writing a
            # duplicate RFQ-004 onto the job.
            sa.UniqueConstraint("project_id", "reference", name="uq_oe_register_workflow_item_ref"),
        )
        op.create_index(f"ix_{_ITEM}_project_id", _ITEM, ["project_id"])
        op.create_index(f"ix_{_ITEM}_kind", _ITEM, ["kind"])
        op.create_index(f"ix_{_ITEM}_status", _ITEM, ["status"])
        op.create_index(f"ix_{_ITEM}_raised_from_id", _ITEM, ["raised_from_id"])
        op.create_index("ix_register_item_project_kind", _ITEM, ["project_id", "kind"])

    if not _has(inspector, _STEP):
        op.create_table(
            _STEP,
            sa.Column("id", guid, primary_key=True),
            sa.Column(
                "item_id",
                guid,
                sa.ForeignKey(f"{_ITEM}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("step_type", sa.String(10), nullable=False, server_default="step"),
            sa.Column("name", sa.String(300), nullable=False),
            sa.Column("owner", sa.String(60), nullable=False, server_default=""),
            sa.Column("branches", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("state", sa.String(20), nullable=False, server_default="open"),
            sa.Column("chosen_branch", sa.String(200), nullable=True),
            sa.Column("completed_by", sa.String(36), nullable=True),
            sa.Column("completed_at", sa.String(40), nullable=True),
            sa.Column("override_reason", sa.Text(), nullable=True),
            sa.Column("raises_kind", sa.String(20), nullable=True),
            sa.Column("raised_reference", sa.String(40), nullable=True),
            sa.Column("is_gate_blocked", sa.Boolean(), nullable=False, server_default="false"),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        )
        op.create_index(f"ix_{_STEP}_item_id", _STEP, ["item_id"])
        op.create_index("ix_register_step_item_pos", _STEP, ["item_id", "position"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Steps first: they carry the FK onto items.
    if _has(inspector, _STEP):
        op.drop_table(_STEP)
    if _has(inspector, _ITEM):
        op.drop_table(_ITEM)
