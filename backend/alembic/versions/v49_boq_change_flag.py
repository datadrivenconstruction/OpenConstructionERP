# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""boq - change flags for positions whose drawing or model moved on.

One new table, ``oe_boq_change_flag`` (model ``BOQChangeFlag``). A row says that
a position was measured from a drawing that has since had a new revision, or is
linked to BIM elements whose model has since had a new version. The estimator
reviews the row and marks it reviewed; nothing here changes a quantity.

This one does NOT need running by hand. It adds a table and nothing else, and
``Base.metadata.create_all`` creates every table the models declare that the
database does not have yet, so a running install that boots the new code gets
the table from the model without an upgrade. The revision exists so that an
install that walks the chain with ``alembic upgrade head`` ends up with exactly
the same table, constraints and indexes: the names below are the ones the
metadata naming convention in ``app.database`` produces.

Inspector-guarded, so a re-run on a database that already has the table, or a
downgrade on one that never got it, changes nothing.

Revision ID: v49_boq_change_flag
Revises: v48_demo_project_tombstone
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v49_boq_change_flag"
down_revision: Union[str, Sequence[str], None] = "v48_demo_project_tombstone"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_boq_change_flag"
_GUID = sa.String(36)


def upgrade() -> None:
    """Create ``oe_boq_change_flag`` with its constraints and indexes."""
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names():
        return
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
        sa.Column("project_id", _GUID, nullable=False),
        sa.Column("boq_id", _GUID, nullable=False),
        sa.Column("position_id", _GUID, nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_key", sa.String(255), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=True),
        sa.Column("source_label", sa.String(500), nullable=False, server_default=""),
        sa.Column("source_version", sa.String(64), nullable=True),
        sa.Column("reason", sa.String(32), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("detected_via", sa.String(16), nullable=False, server_default="scan"),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("reviewed_by", _GUID, nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_note", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_oe_boq_change_flag"),
        sa.ForeignKeyConstraint(
            ["boq_id"],
            ["oe_boq_boq.id"],
            name="fk_oe_boq_change_flag_boq_id_oe_boq_boq",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["position_id"],
            ["oe_boq_position.id"],
            name="fk_oe_boq_change_flag_position_id_oe_boq_position",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "position_id",
            "source_type",
            "source_key",
            name="uq_oe_boq_change_flag_position_id",
        ),
    )
    op.create_index("ix_oe_boq_change_flag_project_id", _TABLE, ["project_id"])
    op.create_index("ix_oe_boq_change_flag_boq_id", _TABLE, ["boq_id"])
    op.create_index("ix_oe_boq_change_flag_position_id", _TABLE, ["position_id"])
    op.create_index("ix_boq_change_flag_boq_status", _TABLE, ["boq_id", "status"])


def downgrade() -> None:
    """Drop ``oe_boq_change_flag``. Open review items are lost with it."""
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names():
        op.drop_table(_TABLE)
