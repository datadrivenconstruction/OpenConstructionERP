# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""propdev: pricing engine — price lists, entries, rules + reservation snapshot.

Adds three tables for the rule-driven property-dev pricing engine:

    oe_property_dev_price_list
    oe_property_dev_price_list_entry
    oe_property_dev_pricing_rule

…and one column on the existing ``oe_property_dev_reservation`` table:

    price_breakdown_snapshot (JSON, NOT NULL, server_default '{}')

The new tables version per-development price catalogues (draft → active →
superseded) with per-plot ``base_price`` entries and an ordered chain of
``PricingRule`` objects (early-bird, view premium, floor premium, corner,
size, promo code, friends & family, loyalty, bulk-buy). The Reservation
snapshot captures the active ``PriceQuote`` at the moment of reservation
create so the audit-trail (Quote History tab) can answer "why did this
deal close at X?".

Strictly additive + inspector-guarded so a fresh ``Base.metadata.create_all``
install followed by ``alembic stamp head`` is a no-op when this migration
runs (matches the post-v3120 fresh-install discipline).

Per the post-v4.4.1 server-default discipline (see issue #154 memory):
every NOT NULL column carries a ``server_default`` so a blank-DB
``create_all`` path can't trip ``IntegrityError`` during seed. Existing
Reservation rows are backfilled in a single ``UPDATE`` so the column
flips to NOT NULL without a window where the constraint is violated.

Money columns are ``Numeric(18, 2)`` — never ``Float``. Percent column
is ``Numeric(6, 3)`` (e.g. -5.000 for a 5 % discount).

Revision ID: v3124_propdev_pricing_engine
Revises: v3123_boq_fk_indexes
Create Date: 2026-05-24
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3125_propdev_pricing_engine"
down_revision: Union[str, Sequence[str], None] = "v3124_propdev_analytics_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Inspector helpers (mirror v3120 pattern) ────────────────────────────


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    name: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def _has_column(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    column: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return column in {c["name"] for c in inspector.get_columns(table)}


def _audit_columns() -> list[sa.Column]:
    """``Base.id / created_at / updated_at`` mirror for raw CREATE TABLE."""
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
    ]


# ── upgrade ─────────────────────────────────────────────────────────────


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    # ── PriceList ───────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_price_list"):
        op.create_table(
            "oe_property_dev_price_list",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "development_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_development.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "name",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "effective_from",
                sa.String(20),
                nullable=False,
                server_default="",
            ),
            sa.Column("effective_to", sa.String(20), nullable=True),
            sa.Column(
                "currency",
                sa.String(8),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="draft",
            ),
            sa.Column("created_by", guid, nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
        )
        if not _has_index(
            inspector,
            "oe_property_dev_price_list",
            "ix_oe_property_dev_price_list_development_id",
        ):
            op.create_index(
                "ix_oe_property_dev_price_list_development_id",
                "oe_property_dev_price_list",
                ["development_id"],
            )
        if not _has_index(
            inspector,
            "oe_property_dev_price_list",
            "ix_oe_property_dev_price_list_status",
        ):
            op.create_index(
                "ix_oe_property_dev_price_list_status",
                "oe_property_dev_price_list",
                ["status"],
            )
        if not _has_index(
            inspector,
            "oe_property_dev_price_list",
            "ix_oe_property_dev_price_list_created_by",
        ):
            op.create_index(
                "ix_oe_property_dev_price_list_created_by",
                "oe_property_dev_price_list",
                ["created_by"],
            )

    # ── PriceListEntry ──────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_price_list_entry"):
        op.create_table(
            "oe_property_dev_price_list_entry",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "price_list_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_price_list.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "plot_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_plot.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "base_price",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.UniqueConstraint(
                "price_list_id",
                "plot_id",
                name="uq_oe_property_dev_price_list_entry_list_plot",
            ),
        )
        if not _has_index(
            inspector,
            "oe_property_dev_price_list_entry",
            "ix_oe_property_dev_price_list_entry_price_list_id",
        ):
            op.create_index(
                "ix_oe_property_dev_price_list_entry_price_list_id",
                "oe_property_dev_price_list_entry",
                ["price_list_id"],
            )
        if not _has_index(
            inspector,
            "oe_property_dev_price_list_entry",
            "ix_oe_property_dev_price_list_entry_plot_id",
        ):
            op.create_index(
                "ix_oe_property_dev_price_list_entry_plot_id",
                "oe_property_dev_price_list_entry",
                ["plot_id"],
            )

    # ── PricingRule ─────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_pricing_rule"):
        op.create_table(
            "oe_property_dev_pricing_rule",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "price_list_id",
                guid,
                sa.ForeignKey(
                    "oe_property_dev_price_list.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "name",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "rule_type",
                sa.String(40),
                nullable=False,
                server_default="early_bird",
            ),
            sa.Column(
                "condition_json",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "adjustment_pct",
                sa.Numeric(6, 3),
                nullable=False,
                server_default="0",
            ),
            sa.Column("adjustment_fixed", sa.Numeric(18, 2), nullable=True),
            sa.Column(
                "priority",
                sa.Integer(),
                nullable=False,
                server_default="100",
            ),
            sa.Column(
                "active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1") if is_sqlite else sa.text("true"),
            ),
            sa.Column(
                "effective_from",
                sa.String(20),
                nullable=False,
                server_default="",
            ),
            sa.Column("effective_to", sa.String(20), nullable=True),
            sa.Column("max_uses", sa.Integer(), nullable=True),
            sa.Column(
                "times_used",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
        )
        if not _has_index(
            inspector,
            "oe_property_dev_pricing_rule",
            "ix_oe_property_dev_pricing_rule_price_list_id",
        ):
            op.create_index(
                "ix_oe_property_dev_pricing_rule_price_list_id",
                "oe_property_dev_pricing_rule",
                ["price_list_id"],
            )
        if not _has_index(
            inspector,
            "oe_property_dev_pricing_rule",
            "ix_oe_property_dev_pricing_rule_rule_type",
        ):
            op.create_index(
                "ix_oe_property_dev_pricing_rule_rule_type",
                "oe_property_dev_pricing_rule",
                ["rule_type"],
            )
        if not _has_index(
            inspector,
            "oe_property_dev_pricing_rule",
            "ix_oe_property_dev_pricing_rule_active",
        ):
            op.create_index(
                "ix_oe_property_dev_pricing_rule_active",
                "oe_property_dev_pricing_rule",
                ["active"],
            )

    # ── Reservation.price_breakdown_snapshot (additive column) ──────────
    # Two-step add-then-backfill-then-flip-NOT-NULL pattern so the column
    # is safe to add to a populated table. SQLite limitations on
    # ALTER TABLE … ALTER COLUMN mean we go via batch_alter on SQLite
    # for the NOT NULL step; on Postgres we use a server_default to fill
    # existing rows in a single statement.
    if not _has_column(
        inspector,
        "oe_property_dev_reservation",
        "price_breakdown_snapshot",
    ):
        if is_sqlite:
            # SQLite path: add NOT NULL + server_default in one go — the
            # default expression is materialised for existing rows.
            with op.batch_alter_table(
                "oe_property_dev_reservation",
            ) as batch_op:
                batch_op.add_column(
                    sa.Column(
                        "price_breakdown_snapshot",
                        sa.JSON(),
                        nullable=False,
                        server_default="{}",
                    )
                )
        else:
            # Postgres path: add nullable, backfill existing rows, then
            # flip to NOT NULL. Avoids a long ACCESS EXCLUSIVE on a
            # populated reservation table.
            op.add_column(
                "oe_property_dev_reservation",
                sa.Column(
                    "price_breakdown_snapshot",
                    sa.JSON(),
                    nullable=True,
                    server_default="{}",
                ),
            )
            # Backfill: surface existing deposit_amount/currency so the
            # historical audit trail at least carries the deposit money
            # we know about.
            op.execute(
                "UPDATE oe_property_dev_reservation "
                "SET price_breakdown_snapshot = "
                "    json_build_object("
                "        'base_price', deposit_amount::text, "
                "        'lines', '[]'::json, "
                "        'total', deposit_amount::text, "
                "        'currency', currency, "
                "        'price_list_id', NULL"
                "    ) "
                "WHERE price_breakdown_snapshot IS NULL "
                "   OR price_breakdown_snapshot::text = '{}'"
            )
            op.alter_column(
                "oe_property_dev_reservation",
                "price_breakdown_snapshot",
                nullable=False,
            )


# ── downgrade ───────────────────────────────────────────────────────────


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"

    # Reservation column — drop first, before tables it references can disappear.
    if _has_column(
        inspector,
        "oe_property_dev_reservation",
        "price_breakdown_snapshot",
    ):
        if is_sqlite:
            with op.batch_alter_table(
                "oe_property_dev_reservation",
            ) as batch_op:
                batch_op.drop_column("price_breakdown_snapshot")
        else:
            op.drop_column(
                "oe_property_dev_reservation",
                "price_breakdown_snapshot",
            )

    for table in (
        "oe_property_dev_pricing_rule",
        "oe_property_dev_price_list_entry",
        "oe_property_dev_price_list",
    ):
        if _has_table(inspector, table):
            op.drop_table(table)
