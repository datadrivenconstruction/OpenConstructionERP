# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Register Workflow: heal the stale UNIQUE-on-prefix counter index.

v0003 moved uniqueness from ``prefix`` alone to ``(prefix, scope)`` - but
databases that ran an early cut of v0003 (both live installs did) kept the
old ``ix_oe_register_workflow_counter_prefix`` as a UNIQUE index. Alembic
records a revision as applied and never re-runs it, so editing v0003 could
not reach them.

The damage was total for per-job numbering: the first job to use a kind
claimed the prefix, and every later job's raise of that kind died on
``duplicate key value violates unique constraint`` - a 500 with nothing
wrong on the screen. Found by the 31 Aug stress pass raising on a second
project.

This revision is the self-heal: drop ANY unique index or constraint on
exactly ``[prefix]``, then make sure the plain (non-unique) index the
model declares exists. Idempotent and inspector-guarded like the others -
a database already in the right shape passes straight through.

Revision ID: oe_register_workflow_v0004_prefix_index_not_unique
Revises: oe_register_workflow_v0003_counter_scope
Create Date: 2026-08-31
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "oe_register_workflow_v0004_prefix_index_not_unique"
down_revision: Union[str, Sequence[str], None] = "oe_register_workflow_v0003_counter_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_COUNTER = "oe_register_workflow_counter"
_IX = f"ix_{_COUNTER}_prefix"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _COUNTER not in inspector.get_table_names():
        return

    # Any UNIQUE constraint on prefix alone: gone.
    for uq in inspector.get_unique_constraints(_COUNTER):
        if uq.get("column_names", uq.get("column_keys")) == ["prefix"] and uq.get("name"):
            op.drop_constraint(uq["name"], _COUNTER, type_="unique")

    # Any UNIQUE index on prefix alone: gone. (This is the shape both live
    # databases actually had - v0002's model made it via index=True +
    # unique, which Postgres stores as an index, not a constraint.)
    for ix in inspector.get_indexes(_COUNTER):
        if ix.get("column_names") == ["prefix"] and ix.get("name") and ix.get("unique"):
            op.drop_index(ix["name"], table_name=_COUNTER)

    # Recreate the plain lookup index the model declares, if it is missing
    # now - re-inspect rather than trusting the pre-drop snapshot.
    have = {i.get("name") for i in sa.inspect(bind).get_indexes(_COUNTER)}
    if _IX not in have:
        op.create_index(_IX, _COUNTER, ["prefix"])


def downgrade() -> None:
    # There is nothing to go back to: the unique-on-prefix world is the
    # bug. Downgrade keeps the healed shape.
    pass
