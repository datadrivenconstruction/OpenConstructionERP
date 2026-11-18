# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""monitoring: settings, profiles, points, epochs, readings, alerts

Additive new tables only, so a deploy that heals its schema at boot picks them
up without ``alembic upgrade``.

Revision ID: vmon01_monitoring
Revises: vlpc01_land_parcels
Create Date: 2026-11-17
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vmon01_monitoring"
down_revision: str | Sequence[str] | None = "vlpc01_land_parcels"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SET = "oe_monitoring_settings"
_PROF = "oe_monitoring_profile"
_PT = "oe_monitoring_point"
_EP = "oe_monitoring_epoch"
_RD = "oe_monitoring_reading"
_AL = "oe_monitoring_alert"


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


def _fk(name: str, target: str) -> sa.Column:
    return sa.Column(name, sa.String(36), sa.ForeignKey(f"{target}.id", ondelete="CASCADE"), nullable=False)


def upgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    if _SET not in existing:
        op.create_table(
            _SET,
            *_base(),
            _project_fk(),
            sa.Column("profile_key", sa.String(80), nullable=False, server_default=""),
            sa.UniqueConstraint("project_id", name="uq_oe_monitoring_settings_project_id"),
        )
    if _PROF not in existing:
        op.create_table(
            _PROF,
            *_base(),
            _project_fk(),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("alert_mm", sa.Numeric(10, 2), nullable=True),
            sa.Column("action_mm", sa.Numeric(10, 2), nullable=True),
            sa.Column("alarm_mm", sa.Numeric(10, 2), nullable=True),
            sa.Column("rate_alert", sa.Numeric(10, 3), nullable=True),
            sa.Column("rate_action", sa.Numeric(10, 3), nullable=True),
            sa.Column("rate_alarm", sa.Numeric(10, 3), nullable=True),
            sa.Column("reference", sa.String(255), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index("ix_oe_monitoring_profile_project", _PROF, ["project_id"])
    if _PT not in existing:
        op.create_table(
            _PT,
            *_base(),
            _project_fk(),
            sa.Column("code", sa.String(64), nullable=False),
            sa.Column("name", sa.String(255), nullable=False, server_default=""),
            sa.Column("point_type", sa.String(32), nullable=False, server_default="settlement_pin"),
            sa.Column("axis", sa.String(16), nullable=False, server_default="z"),
            sa.Column("location", sa.String(255), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", "code", name="uq_oe_monitoring_point_project_code"),
        )
        op.create_index("ix_oe_monitoring_point_project", _PT, ["project_id"])
    if _EP not in existing:
        op.create_table(
            _EP,
            *_base(),
            _project_fk(),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("label", sa.String(255), nullable=False, server_default=""),
            sa.Column("source_filename", sa.String(255), nullable=False, server_default=""),
            sa.Column("imported_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", "observed_at", name="uq_oe_monitoring_epoch_project_at"),
        )
    if _RD not in existing:
        op.create_table(
            _RD,
            *_base(),
            _project_fk(),
            _fk("point_id", _PT),
            _fk("epoch_id", _EP),
            sa.Column("e", sa.Numeric(14, 4), nullable=True),
            sa.Column("n", sa.Numeric(14, 4), nullable=True),
            sa.Column("z", sa.Numeric(14, 4), nullable=True),
            sa.Column("value", sa.Numeric(14, 4), nullable=True),
            sa.UniqueConstraint("point_id", "epoch_id", name="uq_oe_monitoring_reading_point_epoch"),
        )
        op.create_index("ix_oe_monitoring_reading_point", _RD, ["point_id"])
        op.create_index("ix_oe_monitoring_reading_epoch", _RD, ["epoch_id"])
    if _AL not in existing:
        op.create_table(
            _AL,
            *_base(),
            _project_fk(),
            _fk("point_id", _PT),
            _fk("reading_id", _RD),
            sa.Column("level", sa.String(10), nullable=False),
            sa.Column("displacement_mm", sa.Numeric(10, 1), nullable=False),
            sa.Column("rate_mm_day", sa.Numeric(10, 2), nullable=True),
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("profile_label", sa.String(255), nullable=False, server_default=""),
            sa.Column("thresholds", sa.JSON(), nullable=False),
            sa.Column("notified", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("risk_id", sa.String(36), nullable=True),
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("acknowledged_by", sa.String(36), nullable=True),
            sa.Column("acknowledged_by_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
        )
        op.create_index("ix_oe_monitoring_alert_point", _AL, ["point_id"])
        op.create_index("ix_oe_monitoring_alert_project", _AL, ["project_id"])


def downgrade() -> None:
    op.drop_index("ix_oe_monitoring_alert_project", table_name=_AL)
    op.drop_index("ix_oe_monitoring_alert_point", table_name=_AL)
    op.drop_table(_AL)
    op.drop_index("ix_oe_monitoring_reading_epoch", table_name=_RD)
    op.drop_index("ix_oe_monitoring_reading_point", table_name=_RD)
    op.drop_table(_RD)
    op.drop_table(_EP)
    op.drop_index("ix_oe_monitoring_point_project", table_name=_PT)
    op.drop_table(_PT)
    op.drop_index("ix_oe_monitoring_profile_project", table_name=_PROF)
    op.drop_table(_PROF)
    op.drop_table(_SET)
