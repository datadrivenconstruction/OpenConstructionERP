# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""accommodation — initial schema (worker camps + rentals + hotels).

Adds four tables for the Accommodation module:

    oe_accommodation_accommodation
    oe_accommodation_room
    oe_accommodation_booking
    oe_accommodation_charge

Strictly additive + inspector-guarded so a fresh install whose env.py
shortcut applies ``Base.metadata.create_all`` AND stamps the head is a
no-op when this migration runs.

Per the post-v4.4.1 server-default discipline (see issue #154 memory):
every NOT NULL column carries a ``server_default`` so a fresh-blank-DB
``create_all`` path can't trip ``IntegrityError`` during seed.

Money columns are ``Numeric(18, 2)``: NEVER ``Float`` — losing cents on a
single rollup is unacceptable for a billing / housing module.

Revision ID: v3120_accommodation_init
Revises: v3119_propdev_house_type_parking_spots
Create Date: 2026-05-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3120_accommodation_init"
down_revision: Union[str, Sequence[str], None] = "v3119_propdev_house_type_parking_spots"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Inspector helpers ───────────────────────────────────────────────────


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


def upgrade() -> None:  # noqa: C901 — flat sequential CREATE TABLEs.
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    # ── Accommodation ───────────────────────────────────────────────────
    if not _has_table(inspector, "oe_accommodation_accommodation"):
        op.create_table(
            "oe_accommodation_accommodation",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey(
                    "oe_projects_project.id",
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
                "kind",
                sa.String(20),
                nullable=False,
                server_default="worker_camp",
            ),
            sa.Column("address", sa.Text(), nullable=True),
            sa.Column("geo_lat", sa.Numeric(10, 7), nullable=True),
            sa.Column("geo_lon", sa.Numeric(10, 7), nullable=True),
            sa.Column("bim_model_id", guid, nullable=True),
            sa.Column("property_dev_block_id", guid, nullable=True),
            sa.Column(
                "capacity_total",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column(
                "deleted_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        if not _has_index(
            inspector,
            "oe_accommodation_accommodation",
            "ix_oe_accommodation_accommodation_project_id",
        ):
            op.create_index(
                "ix_oe_accommodation_accommodation_project_id",
                "oe_accommodation_accommodation",
                ["project_id"],
            )
        if not _has_index(
            inspector,
            "oe_accommodation_accommodation",
            "ix_oe_accommodation_accommodation_kind",
        ):
            op.create_index(
                "ix_oe_accommodation_accommodation_kind",
                "oe_accommodation_accommodation",
                ["kind"],
            )
        if not _has_index(
            inspector,
            "oe_accommodation_accommodation",
            "ix_oe_accommodation_accommodation_property_dev_block_id",
        ):
            op.create_index(
                "ix_oe_accommodation_accommodation_property_dev_block_id",
                "oe_accommodation_accommodation",
                ["property_dev_block_id"],
            )

    # ── Room ────────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_accommodation_room"):
        op.create_table(
            "oe_accommodation_room",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "accommodation_id",
                guid,
                sa.ForeignKey(
                    "oe_accommodation_accommodation.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("label", sa.String(120), nullable=False),
            sa.Column(
                "capacity",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("bim_element_id", sa.String(120), nullable=True),
            sa.Column(
                "base_rate",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "base_rate_currency",
                sa.String(3),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="available",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.UniqueConstraint(
                "accommodation_id",
                "label",
                name="uq_oe_accommodation_room_accom_label",
            ),
        )
        if not _has_index(
            inspector,
            "oe_accommodation_room",
            "ix_oe_accommodation_room_accommodation_id",
        ):
            op.create_index(
                "ix_oe_accommodation_room_accommodation_id",
                "oe_accommodation_room",
                ["accommodation_id"],
            )
        if not _has_index(
            inspector,
            "oe_accommodation_room",
            "ix_oe_accommodation_room_status",
        ):
            op.create_index(
                "ix_oe_accommodation_room_status",
                "oe_accommodation_room",
                ["accommodation_id", "status"],
            )

    # ── Booking ─────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_accommodation_booking"):
        op.create_table(
            "oe_accommodation_booking",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "room_id",
                guid,
                sa.ForeignKey(
                    "oe_accommodation_room.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "occupant_contact_id",
                guid,
                sa.ForeignKey(
                    "oe_contacts_contact.id",
                    ondelete="SET NULL",
                ),
                nullable=True,
            ),
            sa.Column("occupant_name", sa.String(255), nullable=True),
            sa.Column("check_in", sa.Date(), nullable=False),
            sa.Column("check_out", sa.Date(), nullable=True),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="reserved",
            ),
            sa.Column(
                "source",
                sa.String(20),
                nullable=False,
                server_default="manual",
            ),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        if not _has_index(
            inspector,
            "oe_accommodation_booking",
            "ix_oe_accommodation_booking_room_id",
        ):
            op.create_index(
                "ix_oe_accommodation_booking_room_id",
                "oe_accommodation_booking",
                ["room_id"],
            )
        if not _has_index(
            inspector,
            "oe_accommodation_booking",
            "ix_oe_accommodation_booking_occupant_contact_id",
        ):
            op.create_index(
                "ix_oe_accommodation_booking_occupant_contact_id",
                "oe_accommodation_booking",
                ["occupant_contact_id"],
            )
        if not _has_index(
            inspector,
            "oe_accommodation_booking",
            "ix_oe_accommodation_booking_status",
        ):
            op.create_index(
                "ix_oe_accommodation_booking_status",
                "oe_accommodation_booking",
                ["status"],
            )

    # ── Charge ──────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_accommodation_charge"):
        op.create_table(
            "oe_accommodation_charge",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "booking_id",
                guid,
                sa.ForeignKey(
                    "oe_accommodation_booking.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "kind",
                sa.String(20),
                nullable=False,
                server_default="extra",
            ),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "amount",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "currency",
                sa.String(3),
                nullable=False,
                server_default="",
            ),
            sa.Column("period_start", sa.Date(), nullable=True),
            sa.Column("period_end", sa.Date(), nullable=True),
            sa.Column(
                "status",
                sa.String(20),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )
        if not _has_index(
            inspector,
            "oe_accommodation_charge",
            "ix_oe_accommodation_charge_booking_id",
        ):
            op.create_index(
                "ix_oe_accommodation_charge_booking_id",
                "oe_accommodation_charge",
                ["booking_id"],
            )
        if not _has_index(
            inspector,
            "oe_accommodation_charge",
            "ix_oe_accommodation_charge_status",
        ):
            op.create_index(
                "ix_oe_accommodation_charge_status",
                "oe_accommodation_charge",
                ["status"],
            )


# ── downgrade ──────────────────────────────────────────────────────────


def downgrade() -> None:
    """Drop in reverse FK-dependency order; guard each step."""
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table in (
        "oe_accommodation_charge",
        "oe_accommodation_booking",
        "oe_accommodation_room",
        "oe_accommodation_accommodation",
    ):
        if _has_table(inspector, table):
            op.drop_table(table)
