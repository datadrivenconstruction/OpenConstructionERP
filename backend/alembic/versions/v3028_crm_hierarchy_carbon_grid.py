"""Add account hierarchy + role to CRM and grid-factor table for carbon.

Additive changes for the resources/contracts/crm/carbon module deep-dive:

* ``oe_crm_account.parent_account_id`` (GUID, nullable, indexed, FK self) —
  account hierarchy for owner / GC / sub.
* ``oe_crm_account.role`` (varchar(32), NOT NULL, server_default
  'general_contractor', indexed) — role within the hierarchy.
* New table ``oe_carbon_grid_factor`` — country/year emission factor table
  for Scope-2 lookups. Sourced from IEA / DEFRA / EPA eGRID / UBA.

Revision ID: v3028_crm_hierarchy_carbon_grid
Revises: v3027_service_ticket_source
Created: 2026-05-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3028_crm_hierarchy_carbon_grid"
down_revision: Union[str, Sequence[str], None] = "v3027_service_ticket_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add CRM account hierarchy columns + carbon grid factor table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── CRM account hierarchy ────────────────────────────────────────────
    if "oe_crm_account" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("oe_crm_account")}
        if "parent_account_id" not in existing_cols:
            op.add_column(
                "oe_crm_account",
                sa.Column(
                    "parent_account_id",
                    sa.String(length=36),
                    nullable=True,
                ),
            )
            op.create_index(
                "ix_oe_crm_account_parent_account_id",
                "oe_crm_account",
                ["parent_account_id"],
            )
        if "role" not in existing_cols:
            op.add_column(
                "oe_crm_account",
                sa.Column(
                    "role",
                    sa.String(length=32),
                    nullable=False,
                    server_default="general_contractor",
                ),
            )
            op.create_index(
                "ix_oe_crm_account_role",
                "oe_crm_account",
                ["role"],
            )

    # ── Carbon grid factor catalogue ─────────────────────────────────────
    if "oe_carbon_grid_factor" not in inspector.get_table_names():
        op.create_table(
            "oe_carbon_grid_factor",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("country_code", sa.String(length=8), nullable=False),
            sa.Column("year", sa.Integer, nullable=False),
            sa.Column(
                "factor_kg_co2e_per_kwh",
                sa.Numeric(18, 6),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "method",
                sa.String(length=16),
                nullable=False,
                server_default="location",
            ),
            sa.Column("source", sa.String(length=64), nullable=False, server_default=""),
            sa.Column("notes", sa.Text, nullable=False, server_default=""),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.current_timestamp(),
            ),
        )
        op.create_index(
            "ix_oe_carbon_grid_factor_country_year",
            "oe_carbon_grid_factor",
            ["country_code", "year"],
            unique=True,
        )


def downgrade() -> None:
    """Drop the new column / index / table."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if "oe_carbon_grid_factor" in inspector.get_table_names():
        op.drop_index(
            "ix_oe_carbon_grid_factor_country_year",
            table_name="oe_carbon_grid_factor",
        )
        op.drop_table("oe_carbon_grid_factor")

    if "oe_crm_account" in inspector.get_table_names():
        existing_cols = {c["name"] for c in inspector.get_columns("oe_crm_account")}
        existing_indexes = {i["name"] for i in inspector.get_indexes("oe_crm_account")}
        if "ix_oe_crm_account_role" in existing_indexes:
            op.drop_index("ix_oe_crm_account_role", table_name="oe_crm_account")
        if "ix_oe_crm_account_parent_account_id" in existing_indexes:
            op.drop_index(
                "ix_oe_crm_account_parent_account_id",
                table_name="oe_crm_account",
            )
        if "role" in existing_cols:
            op.drop_column("oe_crm_account", "role")
        if "parent_account_id" in existing_cols:
            op.drop_column("oe_crm_account", "parent_account_id")
