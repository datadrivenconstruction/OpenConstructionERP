"""co_unique_project_code

Inspector-guarded so re-running on an already-migrated database is a no-op. The
boot heal adds unique constraints from the model metadata, so on an install that
has ever started this constraint is already present and an unguarded
``create_unique_constraint`` raises DuplicateObject, which rolls back the whole
upgrade rather than this one revision. Guarded in the same shape as
``v2917_po_number_unique``, which was written as the sibling of this fix for
``oe_procurement_po``.

One difference from that sibling, stated rather than left to be discovered: it
de-duplicates pre-existing rows before creating its constraint and this revision
does not. A database already holding duplicate ``(project_id, code)`` rows will
still fail here, on the data rather than on the constraint already existing.
That is the pre-existing behaviour and the boot heal makes the same choice: it
pre-flights a unique with ``GROUP BY ... HAVING count(*) > 1`` and declines to
add the constraint when duplicates are present, leaving the rows alone.

Revision ID: 85f7cfa6eecf
Revises: 24f9595e16d0
Create Date: 2026-04-19 10:12:50.478344

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "85f7cfa6eecf"
down_revision: Union[str, None] = "24f9595e16d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_changeorders_order"
_UQ = "uq_changeorders_project_code"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_unique(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    for uc in inspector.get_unique_constraints(table):
        if uc.get("name") == name:
            return True
    return False


def upgrade() -> None:
    """Add unique constraint on (project_id, code) for change orders.

    BUG-354: protects against the ``count + 1`` race condition in
    :meth:`ChangeOrderService.create_order`. Without the constraint two
    concurrent requests could both compute ``CO-005`` and both succeed,
    producing duplicate codes for the same project.
    """
    inspector = sa.inspect(op.get_bind())
    if not _has_table(inspector, _TABLE):
        return
    if _has_unique(inspector, _TABLE, _UQ):
        return

    with op.batch_alter_table(_TABLE) as batch:
        batch.create_unique_constraint(_UQ, ["project_id", "code"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if not _has_unique(inspector, _TABLE, _UQ):
        return

    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_constraint(_UQ, type_="unique")
