# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""equipment rate catalogue: catalogues, machines, import profiles, asset link

Additive only (new tables and one nullable column), so a deploy that heals its schema at
boot picks it up without ``alembic upgrade``. Every step is guarded so it is safe on a
database that ``create_all`` already built.

Revision ID: vrc01_equipment_rate_catalogue
Revises: vle01_legal_entity_members_and_identity
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vrc01_equipment_rate_catalogue"
down_revision: str | Sequence[str] | None = "vle01_legal_entity_members_and_identity"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CAT = "oe_equipment_rate_catalogue"
_ITEM = "oe_equipment_rate_item"
_PROFILE = "oe_equipment_rate_profile"
_EQ = "oe_equipment_equipment"


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _index(table: str, name: str, columns: list[str]) -> None:
    inspector = sa.inspect(op.get_bind())
    if table in inspector.get_table_names() and name not in {i["name"] for i in inspector.get_indexes(table)}:
        op.create_index(name, table, columns)


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _CAT not in tables:
        op.create_table(
            _CAT,
            *_stamps(),
            sa.Column("family_id", sa.String(36), nullable=False),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("source_label", sa.String(200), nullable=False, server_default=""),
            sa.Column("licence_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("valid_from", sa.String(10), nullable=False),
            sa.Column("interest_convention", sa.String(40), nullable=False, server_default="average_value"),
            sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("working_days_per_month", sa.Numeric(6, 2), nullable=True),
            sa.Column("standby_factor", sa.Numeric(8, 4), nullable=True),
            sa.Column("breakdown_factor", sa.Numeric(8, 4), nullable=True),
            sa.Column("tolerance_pct", sa.Numeric(8, 2), nullable=True),
        )
    _index(_CAT, "ix_oe_equipment_rate_catalogue_family", ["family_id"])

    if _ITEM not in tables:
        op.create_table(
            _ITEM,
            *_stamps(),
            sa.Column("catalogue_id", sa.String(36), sa.ForeignKey(f"{_CAT}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("category", sa.String(100), nullable=False, server_default=""),
            sa.Column("size_key", sa.String(50), nullable=False, server_default=""),
            sa.Column("value", sa.Numeric(18, 4), nullable=False),
            sa.Column("residual", sa.Numeric(18, 4), nullable=False),
            sa.Column("life_years", sa.Numeric(8, 2), nullable=False),
            sa.Column("months_per_year", sa.Numeric(5, 2), nullable=False),
            sa.Column("interest", sa.Numeric(8, 6), nullable=False),
            sa.Column("repair", sa.Numeric(8, 4), nullable=False),
            sa.Column("hours_per_month", sa.Numeric(8, 2), nullable=True),
            sa.Column("override_monthly_rate", sa.Numeric(18, 4), nullable=True),
            sa.Column("operating_cost_per_hour", sa.Numeric(18, 4), nullable=True),
            sa.UniqueConstraint("catalogue_id", "code", name="uq_oe_equipment_rate_item_code"),
        )
    _index(_ITEM, "ix_oe_equipment_rate_item_catalogue", ["catalogue_id"])

    if _PROFILE not in tables:
        op.create_table(
            _PROFILE,
            *_stamps(),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("layout_key", sa.String(50), nullable=False, server_default="own"),
            sa.Column("mapping", sa.JSON(), nullable=False),
            sa.Column("decimal_comma", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("percent_fields", sa.JSON(), nullable=False),
            sa.UniqueConstraint("name", name="uq_oe_equipment_rate_profile_name"),
        )

    inspector = sa.inspect(op.get_bind())
    if _EQ in inspector.get_table_names() and "rate_item_id" not in {c["name"] for c in inspector.get_columns(_EQ)}:
        op.add_column(
            _EQ,
            sa.Column("rate_item_id", sa.String(36), sa.ForeignKey(f"{_ITEM}.id", ondelete="SET NULL"), nullable=True),
        )
    _index(_EQ, "ix_oe_equipment_equipment_rate_item", ["rate_item_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if _EQ in tables:
        if "ix_oe_equipment_equipment_rate_item" in {i["name"] for i in inspector.get_indexes(_EQ)}:
            op.drop_index("ix_oe_equipment_equipment_rate_item", table_name=_EQ)
        if "rate_item_id" in {c["name"] for c in inspector.get_columns(_EQ)}:
            op.drop_column(_EQ, "rate_item_id")
    for table in (_PROFILE, _ITEM, _CAT):
        if table in tables:
            op.drop_table(table)
