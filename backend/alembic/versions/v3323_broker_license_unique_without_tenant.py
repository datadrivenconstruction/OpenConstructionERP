# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""property_dev: a broker licence number is unique without a tenant too

Adds the partial unique index ``uq_oe_property_dev_broker_license_no_tenant``
on ``oe_property_dev_broker (license_number) WHERE tenant_id IS NULL``.

The table has carried ``uq_oe_property_dev_broker_tenant_license`` on
``(tenant_id, license_number)`` since the brokers shipped, and it reads as if a
licence number were unique per tenant. It is, for brokers that have a tenant.
``tenant_id`` is nullable, SQL treats every NULL as distinct from every other,
so two rows with ``tenant_id`` NULL and the same licence number never collide.
Single-tenant installs, which is the default deployment and every demo, keep
``tenant_id`` NULL on every broker, so on those the licence number was unique
on paper only. The integration test that asserts a second broker with the same
licence is refused has been red since the constraint was written, because the
test runs without a tenant.

A partial unique index is the SQL way to constrain the NULL cohort: a UNIQUE
constraint cannot carry a WHERE clause, and folding NULL into the key with
COALESCE would need an expression index that the boot-time index heal in
``app/core/postgres_migrator.py`` does not reconstruct either. Two objects, one
rule: the constraint keeps covering brokers with a tenant, this index covers
brokers without one. The model declares the same index, so a fresh volume gets
it from ``create_all`` and an upgraded one from here; both end up with one
schema.

Rows that already violate the rule
----------------------------------

``CREATE UNIQUE INDEX`` is not ``NOT VALID``-able: over rows that already
duplicate, PostgreSQL rejects the statement, and since Alembic runs the whole
upgrade in one transaction that rejection would roll back every revision in
the run, not this one. So this revision first asks the table whether the NULL
cohort already holds a duplicated licence number. If it does not, the index is
created. If it does, the index is NOT created; the duplicates are written to
the migration log, one line per licence number with the broker ids that share
it, and the revision completes. Nothing is merged or deleted: two brokers with
one licence may be one agency entered twice or two agencies with a data-entry
error, they carry agreements and accruals of their own, and which of them to
keep is a decision about somebody's money that a migration must not take.

An install left in that state is still protected on the write path: the service
refuses a new broker whose licence is already held by another NULL-tenant
broker with 409 before the database is asked. Once the operator has resolved
the duplicates the index can be added by running this revision's upgrade again
(``alembic downgrade`` one step, then ``upgrade``), or by the same
``CREATE UNIQUE INDEX`` by hand; the guard below makes the re-run a no-op when
the index already exists.

Guarded the way this tree guards every additive DDL, and for the same reason:
the boot path runs ``create_all`` before anybody runs ``alembic upgrade head``,
so on a fresh install the index exists by the time an operator upgrades by hand,
and an unguarded ``CREATE INDEX`` would raise and take every later revision
with it.

Revision ID: v3323_broker_license_unique_without_tenant
Revises: v3322_variation_trace_change_kind
Create Date: 2026-09-08
"""

from __future__ import annotations

import logging

import sqlalchemy as sa
from alembic import op

logger = logging.getLogger("alembic.runtime.migration")

# revision identifiers, used by Alembic.
revision = "v3323_broker_license_unique_without_tenant"
down_revision = "v3322_variation_trace_change_kind"
branch_labels = None
depends_on = None

TABLE = "oe_property_dev_broker"
INDEX = "uq_oe_property_dev_broker_license_no_tenant"


def _has_table(insp: sa.engine.reflection.Inspector, table: str) -> bool:
    return table in insp.get_table_names()


def _has_index(insp: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if not _has_table(insp, table):
        return False
    return name in {ix["name"] for ix in insp.get_indexes(table)}


def _duplicated_licences_without_tenant(bind: sa.engine.Connection) -> list[tuple[str, list[str]]]:
    """Licence numbers held by more than one NULL-tenant broker, with their ids."""
    rows = bind.execute(
        sa.text(
            "SELECT license_number, array_agg(id::text ORDER BY created_at) "
            f'FROM "{TABLE}" WHERE tenant_id IS NULL '
            "GROUP BY license_number HAVING count(*) > 1 ORDER BY license_number"
        )
    ).fetchall()
    return [(str(licence), list(ids)) for licence, ids in rows]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not _has_table(insp, TABLE) or _has_index(insp, TABLE, INDEX):
        return

    duplicates = _duplicated_licences_without_tenant(bind)
    if duplicates:
        logger.warning(
            "%s: %d licence number(s) are shared by several brokers without a tenant; "
            "the unique index %s is NOT created until they are resolved. The service "
            "already refuses new duplicates.",
            TABLE,
            len(duplicates),
            INDEX,
        )
        for licence, ids in duplicates:
            logger.warning("%s: licence %r is held by brokers %s", TABLE, licence, ", ".join(ids))
        return

    op.create_index(
        INDEX,
        TABLE,
        ["license_number"],
        unique=True,
        postgresql_where=sa.text("tenant_id IS NULL"),
    )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _has_index(insp, TABLE, INDEX):
        op.drop_index(INDEX, table_name=TABLE)
