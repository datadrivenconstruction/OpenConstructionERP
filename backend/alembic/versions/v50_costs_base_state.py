# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""costs - remember which market and language each loaded base is in.

One new table, ``oe_costs_base_state`` (model ``CostBaseState``). A row per
loaded cost base says which market its shared work items are priced into, which
language their text is in, and whether a switch is running or was cut off. It
replaces a process-local dict and the browser's storage, which a restart, a
second worker or another browser could not see.

This one does NOT need running by hand. It adds a table and nothing else, and
``Base.metadata.create_all`` creates every table the models declare that the
database does not have yet, so a running install that boots the new code gets
the table from the model without an upgrade. The revision exists so that an
install that walks the chain with ``alembic upgrade head`` ends up with exactly
the same table and constraint: the names below are the ones the metadata naming
convention in ``app.database`` produces.

Inspector-guarded, so a re-run on a database that already has the table, or a
downgrade on one that never got it, changes nothing.

Revision ID: v50_costs_base_state
Revises: v49_boq_change_flag
Create Date: 2026-10-04
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v50_costs_base_state"
down_revision: Union[str, Sequence[str], None] = "v49_boq_change_flag"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_costs_base_state"
_GUID = sa.String(36)


def upgrade() -> None:
    """Create ``oe_costs_base_state`` with its unique region constraint."""
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
        sa.Column("region", sa.String(100), nullable=False),
        sa.Column("text_language", sa.String(16), nullable=True),
        sa.Column("active_market", sa.String(100), nullable=True),
        sa.Column("switching_to", sa.String(100), nullable=True),
        sa.Column("updated_by", _GUID, nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_oe_costs_base_state"),
        sa.UniqueConstraint("region", name="uq_oe_costs_base_state_region"),
    )


def downgrade() -> None:
    """Drop ``oe_costs_base_state``. Every base then reads as state unknown."""
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names():
        op.drop_table(_TABLE)
