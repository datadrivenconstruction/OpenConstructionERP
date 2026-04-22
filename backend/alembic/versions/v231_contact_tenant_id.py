"""v2.3.1 -- add tenant_id to oe_contacts_contact + backfill from created_by.

Context: the Contact module historically used ``created_by`` as an
IDOR fence (the router's ``_require_contact_access`` rejects any caller
whose user id does not match ``created_by``).  That works but leaves
two gaps:

1. Legacy rows with ``created_by IS NULL`` fall through the check and
   become 403 for everyone *including* the author — they were unreachable.
2. Semantics are conflated: ``created_by`` is an audit field ("who
   inserted this row") that should be immutable once written, but it
   was doubling as the tenant gate, so transferring a contact between
   users was indistinguishable from rewriting history.

This migration introduces a dedicated ``tenant_id`` column that carries
the access-gate semantics.  For single-tenant installs (the only shape
we ship today) it equals the creator's user id — contacts are siloed
per user, same effective behaviour as before.  A later migration can
link ``tenant_id`` to a real Tenants table without changing any call
sites.

Backfill: ``tenant_id = created_by`` for every existing row.  Rows with
``created_by IS NULL`` stay NULL — they remain admin-only, matching
current behaviour.

Idempotent — checks live schema and only adds the column / index / data
when missing.

Revision ID: v231_contact_tenant_id
Revises: v230_reporting_schedule
Create Date: 2026-04-22
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v231_contact_tenant_id"
down_revision: Union[str, None] = "v230_reporting_schedule"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "oe_contacts_contact"
INDEX_NAME = "ix_oe_contacts_contact_tenant_id"


def _table_exists(table: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return table in insp.get_table_names()


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def _has_index(table: str, index_name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return False
    return any(ix["name"] == index_name for ix in insp.get_indexes(table))


def upgrade() -> None:
    if not _table_exists(TABLE_NAME):
        return

    added_column = False
    if not _has_column(TABLE_NAME, "tenant_id"):
        op.add_column(
            TABLE_NAME,
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
        )
        added_column = True

    # Backfill tenant_id := created_by for rows missing tenancy.  Re-runs
    # are safe because the WHERE clause only touches rows that still have
    # NULL tenant_id.
    op.execute(
        sa.text(
            f"UPDATE {TABLE_NAME} "
            "SET tenant_id = created_by "
            "WHERE tenant_id IS NULL AND created_by IS NOT NULL"
        ),
    )

    if not _has_index(TABLE_NAME, INDEX_NAME):
        op.create_index(INDEX_NAME, TABLE_NAME, ["tenant_id"])

    # ``added_column`` is intentionally unused past this point — we
    # don't need a second-pass validator because the backfill is a full
    # sweep, but the flag helps local debugging.
    _ = added_column


def downgrade() -> None:
    if _has_index(TABLE_NAME, INDEX_NAME):
        op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
    if _has_column(TABLE_NAME, "tenant_id"):
        with op.batch_alter_table(TABLE_NAME) as batch_op:
            batch_op.drop_column("tenant_id")
