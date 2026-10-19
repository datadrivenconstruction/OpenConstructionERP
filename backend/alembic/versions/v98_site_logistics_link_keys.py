# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""site_logistics - foreign keys on the zone-to-area and delivery-to-transport links.

v78 added ``oe_site_logistics_laydown_zone.site_area_id`` and
``oe_site_logistics_delivery.transport_id`` without a foreign key. Both tables
predate the tables they point at, and the boot heal used to issue such a key
before ``create_all`` had built its target, so the key was refused on every
upgrade. The heal now defers those keys until after ``create_all``
(``app.core.postgres_migrator.heal_deferred_foreign_keys``), and the models
declare them again: ``fk_oe_site_zone_area`` and ``fk_oe_site_delivery_transport``,
both ``ON DELETE SET NULL``, which is what the service already did by hand when
an area or a transport was deleted.

On an ordinary install the boot heal adds the keys and this revision finds them
present. It adds them only where an operator walks the chain by hand. Like the
heal, it adds them ``NOT VALID``: existing rows are not rescanned, new writes
are checked. SQLite cannot add a constraint to an existing table, and its schema
comes from the models anyway, so it is left alone. Each key is added inside a
savepoint, so a refusal leaves the column as v78 shipped it and the upgrade goes
on.

Revision ID: v98_site_logistics_link_keys
Revises: v97_bi_benchmark_set_split_currency
Create Date: 2026-10-17
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v98_site_logistics_link_keys"
down_revision: str | Sequence[str] | None = "v97_bi_benchmark_set_split_currency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = logging.getLogger("alembic.runtime.migration")

#: (constraint name, table, column, referred table)
KEYS: list[tuple[str, str, str, str]] = [
    ("fk_oe_site_zone_area", "oe_site_logistics_laydown_zone", "site_area_id", "oe_site_logistics_area"),
    ("fk_oe_site_delivery_transport", "oe_site_logistics_delivery", "transport_id", "oe_site_logistics_transport"),
]


def _key_names(inspector: sa.engine.reflection.Inspector, table: str) -> set[str]:
    return {fk.get("name") for fk in inspector.get_foreign_keys(table)}


def upgrade() -> None:
    """Add each key when its table, column and target are there and the key is not."""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        logger.info("sqlite: site logistics link keys come from the models, nothing to add")
        return
    for name, table, column, target in KEYS:
        inspector = sa.inspect(bind)
        tables = set(inspector.get_table_names())
        if table not in tables or target not in tables:
            logger.info("%s or %s absent, %s not added", table, target, name)
            continue
        if column not in {c["name"] for c in inspector.get_columns(table)}:
            logger.info("%s.%s absent, %s not added", table, column, name)
            continue
        if name in _key_names(inspector, table):
            continue
        savepoint = bind.begin_nested()
        try:
            op.create_foreign_key(name, table, target, [column], ["id"], ondelete="SET NULL", postgresql_not_valid=True)
        except (sa.exc.OperationalError, sa.exc.ProgrammingError) as exc:  # pragma: no cover - partial install
            savepoint.rollback()
            logger.warning("could not create %s; column kept without the constraint: %r", name, exc)
        else:
            savepoint.commit()


def downgrade() -> None:
    """Drop the two keys where present; the columns and their data stay."""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        return
    for name, table, _column, _target in KEYS:
        inspector = sa.inspect(bind)
        if table in inspector.get_table_names() and name in _key_names(inspector, table):
            op.drop_constraint(name, table, type_="foreignkey")
