# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""property_dev — Plot create-form parity (extra real-estate fields).

Adds the columns the New-Plot UI now exposes to ``oe_property_dev_plot``:

    house_type_label    String(120), nullable          (free-text label;
                                                       superseded once the
                                                       house-type catalogue
                                                       task lands)
    view_type           String(40),  nullable          (sea, mountain, garden,
                                                       courtyard, street, park,
                                                       other)
    balcony_area_m2     Numeric(18,2), nullable
    storage_area_m2     Numeric(18,2), nullable
    bedrooms            Integer, NOT NULL, server_default='0'
    bathrooms           Integer, NOT NULL, server_default='0'
    parking_spaces      Integer, NOT NULL, server_default='0'
    sun_exposure_hours  Numeric(4,2), nullable

Lesson from #154: every NOT NULL column ships a ``server_default`` so
SQLite ``create_all`` and Postgres ALTER both populate existing rows.
The defaults match the SQLAlchemy model declarations.

The migration is inspector-guarded: a fresh-DB install whose tables
were already populated by ``Base.metadata.create_all`` via env.py's
fresh-DB shortcut hits an idempotent no-op here.

SQLite uses ``batch_alter_table`` for the ALTERs (copy + swap pattern
v3103 introduced) so the additions survive on SQLite installs.

Revision ID: v3113_propdev_plot_extra_fields
Revises: v3112_bootstrap_missing_tables
Create Date: 2026-05-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3113_propdev_plot_extra_fields"
down_revision: Union[str, Sequence[str], None] = "v3112_bootstrap_missing_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_property_dev_plot"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    column: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


# Column definitions: (name, factory). The factory takes no args and
# returns a fresh ``sa.Column`` — fresh because batch_alter_table reuses
# the column objects across SQLite passes.
def _column_specs() -> list[tuple[str, sa.Column[object]]]:
    return [
        (
            "house_type_label",
            sa.Column(
                "house_type_label",
                sa.String(120),
                nullable=True,
            ),
        ),
        (
            "view_type",
            sa.Column(
                "view_type",
                sa.String(40),
                nullable=True,
            ),
        ),
        (
            "balcony_area_m2",
            sa.Column(
                "balcony_area_m2",
                sa.Numeric(18, 2),
                nullable=True,
            ),
        ),
        (
            "storage_area_m2",
            sa.Column(
                "storage_area_m2",
                sa.Numeric(18, 2),
                nullable=True,
            ),
        ),
        (
            "bedrooms",
            sa.Column(
                "bedrooms",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        ),
        (
            "bathrooms",
            sa.Column(
                "bathrooms",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        ),
        (
            "parking_spaces",
            sa.Column(
                "parking_spaces",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        ),
        (
            "sun_exposure_hours",
            sa.Column(
                "sun_exposure_hours",
                sa.Numeric(4, 2),
                nullable=True,
            ),
        ),
    ]


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        # Fresh install — create_all already populated everything.
        return

    missing = [(name, col) for (name, col) in _column_specs() if not _has_column(inspector, _TABLE, name)]
    if not missing:
        return

    with op.batch_alter_table(_TABLE) as batch:
        for _name, col in missing:
            batch.add_column(col)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return

    to_drop = [name for (name, _col) in _column_specs() if _has_column(inspector, _TABLE, name)]
    if not to_drop:
        return

    with op.batch_alter_table(_TABLE) as batch:
        for name in to_drop:
            batch.drop_column(name)
