# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""property_dev — Development create-form parity (extra real-estate fields).

The New-Development modal previously asked the user to repeat the active
project pick and exposed only ``code`` + ``name`` + ``total_plots``.
A development is a long-lived business artefact (1:N plots, 1:N phases,
1:N buyers, full sales pipeline) so the bare-bones model was always
going to need filling out — and users called it out as soon as the
duplicate project picker landed.

Adds the columns the rebuilt create form now exposes to
``oe_property_dev_development``:

    description                 Text,            nullable
    dev_type                    String(40),  NOT NULL, server_default='residential'
    country_code                String(2),       nullable  (ISO-3166 alpha-2)
    latitude                    Numeric(10,7),   nullable  (WGS84)
    longitude                   Numeric(10,7),   nullable  (WGS84)
    total_area_m2               Numeric(18,2), NOT NULL, server_default='0'
    total_floors                Integer,       NOT NULL, server_default='0'
    start_date                  String(20),      nullable  (ISO-8601 date)
    sales_target_amount         Numeric(18,2), NOT NULL, server_default='0'
    currency                    String(8),     NOT NULL, server_default=''
    developer_name              String(255),     nullable
    architect_name              String(255),     nullable
    general_contractor_name     String(255),     nullable
    cover_image_url             String(1024),    nullable
    brochure_url                String(1024),    nullable
    website_url                 String(1024),    nullable

Lesson from #154: every NOT NULL column ships a ``server_default`` so
SQLite ``create_all`` and Postgres ALTER both populate existing rows.
The defaults match the SQLAlchemy model declarations exactly.

The migration is inspector-guarded: a fresh-DB install whose tables
were already populated by ``Base.metadata.create_all`` via env.py's
fresh-DB shortcut hits an idempotent no-op here.

SQLite uses ``batch_alter_table`` for the ALTERs (copy + swap pattern
v3103 introduced) so the additions survive on SQLite installs.

Revision ID: v3115_propdev_development_extra_fields
Revises: v3114_propdev_house_type_catalogue
Create Date: 2026-05-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3115_propdev_development_extra_fields"
down_revision: Union[str, Sequence[str], None] = "v3114_propdev_house_type_catalogue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE = "oe_property_dev_development"


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


# Column definitions: (name, factory). batch_alter_table consumes the
# Column objects so we build a fresh list per call.
def _column_specs() -> list[tuple[str, sa.Column[object]]]:
    return [
        ("description", sa.Column("description", sa.Text(), nullable=True)),
        (
            "dev_type",
            sa.Column(
                "dev_type",
                sa.String(40),
                nullable=False,
                server_default="residential",
            ),
        ),
        ("country_code", sa.Column("country_code", sa.String(2), nullable=True)),
        ("latitude", sa.Column("latitude", sa.Numeric(10, 7), nullable=True)),
        ("longitude", sa.Column("longitude", sa.Numeric(10, 7), nullable=True)),
        (
            "total_area_m2",
            sa.Column(
                "total_area_m2",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
        ),
        (
            "total_floors",
            sa.Column(
                "total_floors",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        ),
        ("start_date", sa.Column("start_date", sa.String(20), nullable=True)),
        (
            "sales_target_amount",
            sa.Column(
                "sales_target_amount",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
        ),
        (
            "currency",
            sa.Column(
                "currency",
                sa.String(8),
                nullable=False,
                server_default="",
            ),
        ),
        (
            "developer_name",
            sa.Column(
                "developer_name",
                sa.String(255),
                nullable=True,
            ),
        ),
        (
            "architect_name",
            sa.Column(
                "architect_name",
                sa.String(255),
                nullable=True,
            ),
        ),
        (
            "general_contractor_name",
            sa.Column(
                "general_contractor_name",
                sa.String(255),
                nullable=True,
            ),
        ),
        (
            "cover_image_url",
            sa.Column(
                "cover_image_url",
                sa.String(1024),
                nullable=True,
            ),
        ),
        (
            "brochure_url",
            sa.Column(
                "brochure_url",
                sa.String(1024),
                nullable=True,
            ),
        ),
        (
            "website_url",
            sa.Column(
                "website_url",
                sa.String(1024),
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

    # Add an index on country_code (drives the house-type catalogue +
    # tax-engine country lookup; both run on every plot create).
    inspector = sa.inspect(bind)
    existing_indexes = {idx["name"] for idx in inspector.get_indexes(_TABLE)}
    if "ix_oe_property_dev_development_country_code" not in existing_indexes:
        op.create_index(
            "ix_oe_property_dev_development_country_code",
            _TABLE,
            ["country_code"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _TABLE):
        return

    existing_indexes = {idx["name"] for idx in inspector.get_indexes(_TABLE)}
    if "ix_oe_property_dev_development_country_code" in existing_indexes:
        op.drop_index(
            "ix_oe_property_dev_development_country_code",
            table_name=_TABLE,
        )

    to_drop = [name for (name, _col) in _column_specs() if _has_column(inspector, _TABLE, name)]
    if not to_drop:
        return

    with op.batch_alter_table(_TABLE) as batch:
        for name in to_drop:
            batch.drop_column(name)
