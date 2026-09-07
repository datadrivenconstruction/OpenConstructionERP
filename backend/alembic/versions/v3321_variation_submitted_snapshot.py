# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""variations: the submitted bill is kept, not only its total

Adds ``submitted_boq_snapshot_id`` to ``oe_variations_request``.

Issue #435. Submitting a variation request already freezes which bill was put
in front of the approver and at what total (``v3317_variation_agreed_value``).
A total is the right thing to agree against and the wrong thing to defend a
price with: the bill goes on being revised after submission, which is the
normal way a variation gets negotiated, and once it has moved nothing can say
which lines, at which quantities and rates, the frozen figure was made of.

The BOQ module already keeps point-in-time copies of a bill in
``oe_boq_snapshot`` (positions and markups as JSON) for its version history.
Submission now writes one of those and this column names it, so "what did the
approver see" is answered by the bill's own history rather than by a number
with no lines behind it.

Nullable, no default, no backfill. A request submitted before this revision
has no copy of its bill as submitted, and nothing can reconstruct one now; a
request with no bill has nothing to copy. Both read back NULL and mean it.

No foreign key, for the same reason ``submitted_boq_id`` carries none: the
snapshot is deleted with its bill (``ON DELETE CASCADE`` on the snapshot
table), and the request's record of what was submitted must not stop that
delete or be nulled by it in a way the request cannot tell from "never had a
bill". The id stays; the reader that follows it learns the bill is gone.

Guarded the way this tree guards ``create_table``, and for the same failure:
the boot path runs ``Base.metadata.create_all`` before anybody can run
``alembic upgrade head``, so on a real install the column already exists by
the time an operator upgrades by hand. An unguarded ``ADD COLUMN`` raises
DuplicateColumn, rolls back the whole upgrade rather than this revision, and
takes every later revision with it.

Revision ID: v3321_variation_submitted_snapshot
Revises: v3320_boq_position_norm_provenance
Create Date: 2026-09-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.database import GUID

# revision identifiers, used by Alembic.
revision: str = "v3321_variation_submitted_snapshot"
down_revision: Union[str, Sequence[str], None] = "v3320_boq_position_norm_provenance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "oe_variations_request"
COLUMN = "submitted_boq_snapshot_id"


def _has_table(insp: sa.engine.reflection.Inspector, table: str) -> bool:
    return table in insp.get_table_names()


def _has_column(insp: sa.engine.reflection.Inspector, table: str, column: str) -> bool:
    if not _has_table(insp, table):
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if not _has_table(insp, TABLE) or _has_column(insp, TABLE, COLUMN):
        return
    # GUID, not a String: ``GUID`` compiles to the same column type
    # ``create_all`` builds from the model, so a fresh volume and an upgraded
    # one end up with one schema rather than two that each look right alone.
    op.add_column(TABLE, sa.Column(COLUMN, GUID(), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _has_column(insp, TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
