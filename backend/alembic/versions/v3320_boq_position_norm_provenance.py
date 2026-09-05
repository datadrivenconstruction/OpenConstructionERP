# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""boq: which production norm a position was priced from, as a column

Adds ``norm_id`` and ``norm_work_key`` to ``oe_boq_position``.

The identity was already being written, into ``metadata["norm_id"]`` and
``metadata["work_key"]``, by the path that applies an assembly to a bill. A JSON
key is enough to record a fact and not enough to answer a question about it. The
only reader of comparable provenance on this table, the assembly usage count,
shows what that costs: it cannot GROUP BY, so it pre-filters with
``metadata::text ILIKE '%"assembly_id": "<id>"%'`` and depends on the exact
spacing the JSON serialiser happens to emit. A per-norm rollup over a whole bill
built on that would be a full scan matched by string shape. So the identity
becomes a column, and the same reasoning that put ``work_key`` beside ``norm_id``
in the metadata keeps them together here: the key is the human handle and it has
to survive the deletion of the row it names.

Both nullable, no default, no backfill of judgement onto rows that carry none.
Most positions on a real bill are typed by hand or imported from a workbook and
were never priced from a norm at all, and there is no value that means "no norm"
other than the absence of one. This is the failure ``price_basis`` documented one
revision family ago: a default here would put a provenance claim on every row
that already exists.

That is also the answer to the NOT NULL question rather than a dodge of it. An
``ADD COLUMN ... NOT NULL`` with no default is rejected outright by PostgreSQL on
a non-empty table, and the shape that does succeed - add nullable, backfill,
then ``SET NOT NULL`` - needs a value to backfill with, which is exactly what
does not exist here. Nullable is the correct type for the fact, not a concession
to the mechanics of adding it.

There IS a backfill, and it is of a different kind: the write side shipped on
2026-09-03 and the column does not exist until this revision, so every bill
priced from a norm in between carries the identity in ``metadata`` with a NULL
column. Those rows are copied across below. It is a copy of a value the row
already holds, not an invention of one, so it cannot claim anything the row was
not already claiming. The read side coalesces column then metadata anyway, so a
row this backfill cannot reach - one written by an older application binary
against this schema - is still answered correctly; the backfill is what keeps
the column worth grouping by rather than what makes the feature work.

Which is worth being precise about, because ``oe_boq_position`` is one of the
five tables ``scripts/check_migration_data_rewrites.py`` names as the shape that
bit hardest in #126: one row per real item of work, small on every demo box and
large after a few years of real projects. The cost that mattered there was
writing a new tuple for every row of a big table inside the single transaction
Alembic wraps ``upgrade()`` in. This does not do that. The predicate is
``norm_id IS NULL AND metadata ->> 'norm_id' IS NOT NULL``, so the number of
tuples written is the number of positions priced from a production norm in the
two days between the write side shipping and this revision - near zero on every
install, and zero on one that has never used the norm library. The read is a
sequential scan of the table either way, since there is no index over a JSON
expression, and a scan is not a rewrite. The tuples written, not the tuples
examined, are what filled the disk in #126.

Guarded the way this tree guards every ``ADD COLUMN``, and for the same failure
v3316 sets out: the boot path runs ``Base.metadata.create_all`` before anybody
can run ``alembic upgrade head``, so on a real install these columns already
exist by the time an operator runs the migration by hand, and an unguarded add
raises ``DuplicateColumn`` inside the transaction that carries every later
revision with it.

Revision ID: v3320_boq_position_norm_provenance
Revises: v3319_project_country_code_nullable
Create Date: 2026-09-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.database import GUID

# revision identifiers, used by Alembic.
revision: str = "v3320_boq_position_norm_provenance"
down_revision: Union[str, Sequence[str], None] = "v3319_project_country_code_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE = "oe_boq_position"

# data-rewrite-ack: table=oe_boq_position growth=tenure rows=one per real item of work, so it tracks operational history and is large on a mature install - small on every demo box, which is why a size measured there would not answer anything; the acknowledged rewrite writes only rows priced from a production norm in the two days between the write side shipping on 2026-09-03 and this revision, which is near zero everywhere and exactly zero on an install that has never used the norm library, so the tuples written do not scale with the table even though the scan does, see #457


def _has_table(insp: sa.engine.reflection.Inspector, table: str) -> bool:
    return table in insp.get_table_names()


def _has_column(insp: sa.engine.reflection.Inspector, table: str, column: str) -> bool:
    if not _has_table(insp, table):
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


# The two statements, module-level so a test can run exactly what ships rather
# than a copy of it that can drift away from it.
#
# No ``::uuid`` cast anywhere, and the reason is not the one it looks like.
# ``app.database.GUID`` is a TypeDecorator over ``String(36)`` on EVERY dialect -
# it has no ``load_dialect_impl`` and never emits a native PostgreSQL ``uuid`` -
# so ``norm_id`` is a ``varchar(36)`` holding the canonical text form. The
# tempting conclusion is that ``SET norm_id = (metadata ->> 'norm_id')::uuid``
# would therefore be rejected. It is not: uuid to text is an ASSIGNMENT cast in
# PostgreSQL, so that statement runs and stores the right value. Measured, on
# this schema, rather than reasoned about - the reasoning gave the wrong answer.
#
# The cast is left out because of what it does on bad input, not on good. It
# raises on a value that is not a uuid, and it raises inside the single
# transaction Alembic wraps ``upgrade()`` in, so one malformed id in one
# customer's metadata would roll back this revision and every later one with it,
# leaving ``alembic_version`` where it was. ``metadata`` is free-form JSON that
# clients write, so malformed ids are data rather than an impossibility. The
# regex predicate below skips those rows instead, and skipping is the behaviour
# a repair wants: the row keeps its metadata, the read side coalesces onto it,
# and nothing else in the chain is held hostage to it.
#
# ``lower()`` then does the one useful thing the cast would have done for free.
# ``str(uuid.UUID(...))`` is lower case and that is what the application writes,
# so a backfilled row that kept an upper-case spelling from the metadata would
# be a different string in a GROUP BY and would split one norm's work in two.
_BACKFILL_NORM_ID_SQL = """
UPDATE oe_boq_position
   SET norm_id = lower(metadata ->> 'norm_id')
 WHERE norm_id IS NULL
   AND metadata ->> 'norm_id' IS NOT NULL
   AND metadata ->> 'norm_id' ~
       '^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$'
"""

# The work key is copied only where the id landed, so the two columns can never
# disagree about whether this row was priced from a norm.
_BACKFILL_WORK_KEY_SQL = """
UPDATE oe_boq_position
   SET norm_work_key = left(metadata ->> 'work_key', 120)
 WHERE norm_work_key IS NULL
   AND norm_id IS NOT NULL
   AND metadata ->> 'work_key' IS NOT NULL
"""


def _backfill_from_metadata(bind: sa.engine.Connection) -> None:
    """Copy ``metadata['norm_id']`` / ``['work_key']`` into the new columns.

    Only rows that already carry the identity and have not been filled in, so
    running it twice changes nothing and a row somebody has since corrected by
    hand is left alone.

    PostgreSQL only. The ``metadata`` column is ``JSON`` rather than ``JSONB``,
    so the operators are the single-arrow text extractors, and the whole thing is
    skipped on any other dialect: SQLite is a development convenience here and a
    development database has no backlog of rows to repair.
    """
    if bind.dialect.name != "postgresql":
        return

    bind.execute(sa.text(_BACKFILL_NORM_ID_SQL))
    bind.execute(sa.text(_BACKFILL_WORK_KEY_SQL))


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)

    if not _has_table(insp, TABLE):
        return

    if not _has_column(insp, TABLE, "norm_id"):
        # GUID rather than a plain String(36): this is an id, it is compared
        # against ``oe_norm_expansion_norm.id``, and the platform's own GUID
        # type is what makes that comparison work identically on both dialects.
        op.add_column(TABLE, sa.Column("norm_id", GUID(), nullable=True))
        op.create_index("ix_oe_boq_position_norm_id", TABLE, ["norm_id"])

    if not _has_column(insp, TABLE, "norm_work_key"):
        # 120 characters, matching ``oe_norm_expansion_norm.work_key`` exactly,
        # so a key that fits in the library cannot be truncated on the way onto
        # a bill.
        op.add_column(TABLE, sa.Column("norm_work_key", sa.String(length=120), nullable=True))

    # No foreign key to the norm table. The whole reason the identity is copied
    # rather than resolved is that the norm library is editable and deletable
    # after a bill has been priced from it, and a foreign key would either block
    # that deletion or null the provenance out on cascade. Both outcomes lose
    # the fact this column exists to keep.

    _backfill_from_metadata(bind)


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())

    if _has_column(insp, TABLE, "norm_work_key"):
        op.drop_column(TABLE, "norm_work_key")
    if _has_column(insp, TABLE, "norm_id"):
        if any(ix["name"] == "ix_oe_boq_position_norm_id" for ix in insp.get_indexes(TABLE)):
            op.drop_index("ix_oe_boq_position_norm_id", table_name=TABLE)
        op.drop_column(TABLE, "norm_id")
