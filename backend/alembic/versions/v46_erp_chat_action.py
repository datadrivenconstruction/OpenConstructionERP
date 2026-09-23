# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""erp_chat - record every change the assistant proposes and who decided it.

One new table, ``oe_erp_chat_action`` (model ``ChatAction``). The assistant no
longer writes domain records on its own: a write tool stores a ``proposed`` row
here, and the record it describes is created or changed only when a person
applies the row. The row keeps what the model proposed, what the person edited,
who approved or rejected it and when, the record it produced, and an undo.

This one does NOT need running by hand. It adds a table and nothing else, and
``Base.metadata.create_all`` creates every table the models declare that the
database does not have yet, so a running install that boots the new code gets
the table from the model without an upgrade. The revision exists so that an
install that walks the chain with ``alembic upgrade head`` ends up with exactly
the same table, indexes and foreign key: the names below are the ones the
metadata naming convention in ``app.database`` produces, so both routes build
the same schema.

Identity columns are ``VARCHAR(36)`` because that is how ``GUID`` renders on
every dialect (see ``v41_smart_views`` for what a native UUID column did to a
foreign key onto a ``VARCHAR(36)`` primary key).

Inspector-guarded, so a re-run on a database that already has the table, or a
downgrade on one that never got it, changes nothing.

Revision ID: v46_erp_chat_action
Revises: v45_claim_gross_basis
Create Date: 2026-09-23
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v46_erp_chat_action"
down_revision: Union[str, Sequence[str], None] = "v45_claim_gross_basis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_erp_chat_action"
_SESSION_TABLE = "oe_erp_chat_session"
_GUID = sa.String(36)

# (index name, column) exactly as ``ix_%(column_0_label)s`` renders them.
_INDEXES: tuple[tuple[str, str], ...] = (
    ("ix_oe_erp_chat_action_session_id", "session_id"),
    ("ix_oe_erp_chat_action_project_id", "project_id"),
    ("ix_oe_erp_chat_action_requested_by", "requested_by"),
    ("ix_oe_erp_chat_action_status", "status"),
    ("ix_oe_erp_chat_action_batch_id", "batch_id"),
)


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _index_names(inspector: sa.engine.reflection.Inspector, table: str) -> set[str]:
    if not _has_table(inspector, table):
        return set()
    return {name for ix in inspector.get_indexes(table) if (name := ix["name"]) is not None}


def upgrade() -> None:
    """Create ``oe_erp_chat_action`` with its indexes and session foreign key."""
    inspector = sa.inspect(op.get_bind())
    if not _has_table(inspector, _TABLE):
        session_fk: list[sa.ForeignKeyConstraint] = []
        if _has_table(inspector, _SESSION_TABLE):
            session_fk.append(
                sa.ForeignKeyConstraint(
                    ["session_id"],
                    [f"{_SESSION_TABLE}.id"],
                    name="fk_oe_erp_chat_action_session_id_oe_erp_chat_session",
                    ondelete="SET NULL",
                )
            )
        op.create_table(
            _TABLE,
            sa.Column("id", _GUID, nullable=False),
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
            sa.Column("session_id", _GUID, nullable=True),
            sa.Column("message_id", _GUID, nullable=True),
            sa.Column("project_id", _GUID, nullable=True),
            sa.Column("requested_by", _GUID, nullable=False),
            sa.Column("action_type", sa.String(64), nullable=False),
            sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("summary", sa.Text(), nullable=True),
            sa.Column("original_payload", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("preview", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("rationale", sa.Text(), nullable=True),
            sa.Column("target_entity_type", sa.String(64), nullable=True),
            sa.Column("target_entity_id", sa.String(64), nullable=True),
            sa.Column("before_state", sa.JSON(), nullable=True),
            sa.Column("decided_by", _GUID, nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_note", sa.Text(), nullable=True),
            sa.Column("applied_entity_type", sa.String(64), nullable=True),
            sa.Column("applied_entity_id", sa.String(64), nullable=True),
            sa.Column("result", sa.JSON(), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            sa.Column("error_code", sa.String(64), nullable=True),
            sa.Column("reverted_by", _GUID, nullable=True),
            sa.Column("reverted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revert_note", sa.Text(), nullable=True),
            sa.Column("batch_id", sa.String(64), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_oe_erp_chat_action"),
            *session_fk,
        )
        inspector = sa.inspect(op.get_bind())

    existing = _index_names(inspector, _TABLE)
    for name, column in _INDEXES:
        if name not in existing:
            op.create_index(name, _TABLE, [column])


def downgrade() -> None:
    """Drop ``oe_erp_chat_action``. The proposals and their audit story go with it."""
    inspector = sa.inspect(op.get_bind())
    if not _has_table(inspector, _TABLE):
        return
    existing = _index_names(inspector, _TABLE)
    for name, _column in _INDEXES:
        if name in existing:
            op.drop_index(name, table_name=_TABLE)
    op.drop_table(_TABLE)
