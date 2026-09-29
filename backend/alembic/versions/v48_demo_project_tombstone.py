# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""projects - remember the demo projects a user removed.

One new table, ``oe_projects_demo_tombstone`` (model ``DemoProjectTombstone``).
A purge of demo data removed the demo project rows, and with them the only
thing that stopped the boot installers from creating the same demos again. An
install whose demo-seed choice file was lost, or whose ``SEED_DEMO`` is set in
the environment, got every purged showcase project back on the next start. The
table holds one row per removed ``demo_id``, and the boot installers skip what
it names.

This one does NOT need running by hand. It adds a table and nothing else, and
``Base.metadata.create_all`` creates every table the models declare that the
database does not have yet, so a running install that boots the new code gets
the table from the model without an upgrade. The revision exists so that an
install that walks the chain with ``alembic upgrade head`` ends up with exactly
the same table and constraint: the names below are the ones the metadata naming
convention in ``app.database`` produces.

Inspector-guarded, so a re-run on a database that already has the table, or a
downgrade on one that never got it, changes nothing.

Revision ID: v48_demo_project_tombstone
Revises: v47_subcontract_agreement_contract
Create Date: 2026-09-29
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v48_demo_project_tombstone"
down_revision: Union[str, Sequence[str], None] = "v47_subcontract_agreement_contract"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_projects_demo_tombstone"
_GUID = sa.String(36)


def upgrade() -> None:
    """Create ``oe_projects_demo_tombstone``."""
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
        sa.Column("demo_id", sa.String(100), nullable=False),
        sa.Column("removed_project_id", _GUID, nullable=True),
        sa.Column("reason", sa.String(16), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_oe_projects_demo_tombstone"),
        sa.UniqueConstraint("demo_id", name="uq_oe_projects_demo_tombstone_demo_id"),
    )


def downgrade() -> None:
    """Drop ``oe_projects_demo_tombstone``. Removed demos may be installed again."""
    inspector = sa.inspect(op.get_bind())
    if _TABLE in inspector.get_table_names():
        op.drop_table(_TABLE)
