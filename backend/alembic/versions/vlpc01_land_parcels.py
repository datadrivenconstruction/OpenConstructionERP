# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""land and parcels: parcels, boundary points, parties, rights, work zones, settings

Additive new tables only, so a deploy that heals its schema at boot picks them
up without ``alembic upgrade``.

Revision ID: vlpc01_land_parcels
Revises: vsto01_setting_out
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vlpc01_land_parcels"
down_revision: str | Sequence[str] | None = "vsto01_setting_out"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PARCEL = "oe_land_parcel"
_POINT = "oe_land_parcel_point"
_PARTY = "oe_land_party"
_RIGHT = "oe_land_right"
_ZONE = "oe_land_work_zone"
_SETTINGS = "oe_land_parcel_settings"


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    ]


def _project_fk() -> sa.Column:
    return sa.Column(
        "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if _PARCEL not in existing:
        op.create_table(
            _PARCEL,
            *_base(),
            _project_fk(),
            sa.Column("parcel_ref", sa.String(100), nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("legal_area", sa.Numeric(16, 4), nullable=True),
            sa.Column("computed_area", sa.Numeric(16, 4), nullable=True),
            sa.Column("ring_closed", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("epsg", sa.Integer(), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="needed"),
            sa.Column("acquisition_cost", sa.Numeric(18, 2), nullable=True),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("acquired_on", sa.Date(), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("source_filename", sa.String(255), nullable=False, server_default=""),
            sa.Column("boq_position_id", sa.String(36), nullable=True),
            sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("sent_by", sa.String(36), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_land_parcel_project", _PARCEL, ["project_id"])
    if _POINT not in existing:
        op.create_table(
            _POINT,
            *_base(),
            sa.Column("parcel_id", sa.String(36), sa.ForeignKey(f"{_PARCEL}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
            sa.Column("label", sa.String(64), nullable=False, server_default=""),
            sa.Column("e", sa.Numeric(14, 4), nullable=False),
            sa.Column("n", sa.Numeric(14, 4), nullable=False),
            sa.Column("mark", sa.String(30), nullable=False, server_default=""),
            sa.Column("accuracy_m", sa.Numeric(8, 4), nullable=True),
        )
        op.create_index("ix_oe_land_parcel_point_parcel", _POINT, ["parcel_id"])
    if _PARTY not in existing:
        op.create_table(
            _PARTY,
            *_base(),
            _project_fk(),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="person"),
            sa.Column("reference", sa.String(255), nullable=False, server_default=""),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
        )
        op.create_index("ix_oe_land_party_project", _PARTY, ["project_id"])
    if _RIGHT not in existing:
        op.create_table(
            _RIGHT,
            *_base(),
            _project_fk(),
            sa.Column("parcel_id", sa.String(36), sa.ForeignKey(f"{_PARCEL}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("party_id", sa.String(36), sa.ForeignKey(f"{_PARTY}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("kind", sa.String(20), nullable=False, server_default="ownership"),
            sa.Column("share", sa.String(20), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("registry_ref", sa.String(255), nullable=False, server_default=""),
            sa.Column("valid_from", sa.Date(), nullable=True),
            sa.Column("valid_to", sa.Date(), nullable=True),
        )
        op.create_index("ix_oe_land_right_parcel", _RIGHT, ["parcel_id"])
    if _ZONE not in existing:
        op.create_table(
            _ZONE,
            *_base(),
            _project_fk(),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("ring", sa.JSON(), nullable=False),
            sa.Column("epsg", sa.Integer(), nullable=True),
            sa.Column("source_filename", sa.String(255), nullable=False, server_default=""),
        )
        op.create_index("ix_oe_land_work_zone_project", _ZONE, ["project_id"])
    if _SETTINGS not in existing:
        op.create_table(
            _SETTINGS,
            *_base(),
            _project_fk(),
            sa.Column("area_tolerance_pct", sa.Numeric(6, 3), nullable=False, server_default="1"),
            sa.Column("gap_tolerance_m", sa.Numeric(8, 3), nullable=False, server_default="0.05"),
            sa.UniqueConstraint("project_id", name="uq_oe_land_parcel_settings_project_id"),
        )


def downgrade() -> None:
    op.drop_table(_SETTINGS)
    op.drop_index("ix_oe_land_work_zone_project", table_name=_ZONE)
    op.drop_table(_ZONE)
    op.drop_index("ix_oe_land_right_parcel", table_name=_RIGHT)
    op.drop_table(_RIGHT)
    op.drop_index("ix_oe_land_party_project", table_name=_PARTY)
    op.drop_table(_PARTY)
    op.drop_index("ix_oe_land_parcel_point_parcel", table_name=_POINT)
    op.drop_table(_POINT)
    op.drop_index("ix_oe_land_parcel_project", table_name=_PARCEL)
    op.drop_table(_PARCEL)
