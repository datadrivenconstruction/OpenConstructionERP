# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""QMS: ITP template library + calibration tracking. HSE: JSA library, PTW prereq, CAPA 5-Whys.

Adds the following tables:

* ``oe_qms_itp_template`` — tenant-level reusable ITP templates
* ``oe_qms_calibration`` — instrument calibration certificates
* ``oe_hse_advanced_jsa_template`` — tenant-level reusable JSA templates

Adds the following columns:

* ``oe_hse_advanced_capa.five_whys`` (JSON) — structured root-cause chain
* ``oe_hse_advanced_capa.effectiveness_verified_at`` (timestamp)
* ``oe_hse_advanced_capa.effectiveness_verified_by`` (GUID)
* ``oe_hse_advanced_ptw.prereq_jsa_approved`` (boolean default false)
* ``oe_hse_advanced_ptw.prereq_supervisor_present`` (boolean default false)
* ``oe_hse_advanced_ptw.prereq_fire_watch_assigned`` (boolean default false)
* ``oe_hse_advanced_ptw.prereq_extinguisher_present`` (boolean default false)
* ``oe_hse_advanced_ptw.prereq_atmospheric_test_passed`` (boolean default false)

All operations are idempotent — re-running on a DB where the columns/tables
already exist is a no-op.

Revision ID: v3029_qms_calibration_template_hse_extras
Revises: v3028_crm_hierarchy_carbon_grid
Created: 2026-05-13
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3029_qms_calibration_template_hse_extras"
down_revision: Union[str, Sequence[str], None] = "v3028_crm_hierarchy_carbon_grid"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_column(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    column: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(c["name"] == column for c in inspector.get_columns(table))


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    index: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def _safe_create_index(name: str, table: str, cols: list[str]) -> None:
    try:
        op.create_index(name, table, cols)
    except sa.exc.OperationalError:
        pass


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    def _id_cols() -> list[sa.Column]:
        return [
            sa.Column("id", guid_type, primary_key=True),
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

    # 1) oe_qms_itp_template
    if not _has_table(inspector, "oe_qms_itp_template"):
        op.create_table(
            "oe_qms_itp_template",
            *_id_cols(),
            sa.Column("csi_division", sa.String(16), nullable=False),
            sa.Column("work_type", sa.String(100), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("standard_ref", sa.String(64), nullable=True),
            sa.Column(
                "items_json",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1" if is_sqlite else "true"),
            ),
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("created_by", sa.String(36), nullable=True),
        )

    # 2) oe_qms_calibration
    if not _has_table(inspector, "oe_qms_calibration"):
        op.create_table(
            "oe_qms_calibration",
            *_id_cols(),
            sa.Column("project_id", guid_type, nullable=True),
            sa.Column("instrument_id", sa.String(100), nullable=False),
            sa.Column("instrument_name", sa.String(255), nullable=False),
            sa.Column("instrument_type", sa.String(100), nullable=False),
            sa.Column("serial_number", sa.String(100), nullable=True),
            sa.Column("manufacturer", sa.String(255), nullable=True),
            sa.Column("calibration_date", sa.Date(), nullable=False),
            sa.Column("valid_until", sa.Date(), nullable=False),
            sa.Column("calibrated_by", sa.String(255), nullable=True),
            sa.Column("certificate_url", sa.String(2000), nullable=True),
            sa.Column("reference_standard", sa.String(255), nullable=True),
            sa.Column("measurement_uncertainty", sa.String(255), nullable=True),
            sa.Column("owner_user_id", guid_type, nullable=True),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="valid",
            ),
            sa.Column("notes", sa.Text(), nullable=True),
        )

    # 3) oe_hse_advanced_jsa_template
    if not _has_table(inspector, "oe_hse_advanced_jsa_template"):
        op.create_table(
            "oe_hse_advanced_jsa_template",
            *_id_cols(),
            sa.Column("trade", sa.String(100), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("task_description", sa.Text(), nullable=False),
            sa.Column(
                "hazards_json",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "required_ppe_json",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column("region", sa.String(32), nullable=True),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1" if is_sqlite else "true"),
            ),
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("created_by", sa.String(36), nullable=True),
        )

    # 4) Additive columns on oe_hse_advanced_capa
    for col_name, col_def in (
        ("five_whys", sa.Column("five_whys", sa.JSON(), nullable=True)),
        (
            "effectiveness_verified_at",
            sa.Column(
                "effectiveness_verified_at",
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        ),
        (
            "effectiveness_verified_by",
            sa.Column("effectiveness_verified_by", guid_type, nullable=True),
        ),
    ):
        if not _has_column(inspector, "oe_hse_advanced_capa", col_name):
            with op.batch_alter_table("oe_hse_advanced_capa") as batch:
                batch.add_column(col_def)

    # 5) Additive columns on oe_hse_advanced_ptw (PTW prerequisites)
    for col_name in (
        "prereq_jsa_approved",
        "prereq_supervisor_present",
        "prereq_fire_watch_assigned",
        "prereq_extinguisher_present",
        "prereq_atmospheric_test_passed",
    ):
        if not _has_column(inspector, "oe_hse_advanced_ptw", col_name):
            with op.batch_alter_table("oe_hse_advanced_ptw") as batch:
                batch.add_column(
                    sa.Column(
                        col_name,
                        sa.Boolean(),
                        nullable=False,
                        server_default=sa.text("0" if is_sqlite else "false"),
                    ),
                )

    # Indexes
    inspector = sa.inspect(bind)
    for name, table, cols in (
        ("ix_oe_qms_itp_template_csi", "oe_qms_itp_template", ["csi_division"]),
        ("ix_oe_qms_itp_template_work_type", "oe_qms_itp_template", ["work_type"]),
        (
            "ix_oe_qms_calibration_project_id",
            "oe_qms_calibration",
            ["project_id"],
        ),
        (
            "ix_oe_qms_calibration_instrument_id",
            "oe_qms_calibration",
            ["instrument_id"],
        ),
        (
            "ix_oe_qms_calibration_valid_until",
            "oe_qms_calibration",
            ["valid_until"],
        ),
        (
            "ix_oe_qms_calibration_status",
            "oe_qms_calibration",
            ["status"],
        ),
        (
            "ix_oe_hse_advanced_jsa_template_trade",
            "oe_hse_advanced_jsa_template",
            ["trade"],
        ),
    ):
        if not _has_index(inspector, table, name):
            _safe_create_index(name, table, cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop indexes
    for name, table in (
        ("ix_oe_qms_itp_template_csi", "oe_qms_itp_template"),
        ("ix_oe_qms_itp_template_work_type", "oe_qms_itp_template"),
        ("ix_oe_qms_calibration_project_id", "oe_qms_calibration"),
        ("ix_oe_qms_calibration_instrument_id", "oe_qms_calibration"),
        ("ix_oe_qms_calibration_valid_until", "oe_qms_calibration"),
        ("ix_oe_qms_calibration_status", "oe_qms_calibration"),
        (
            "ix_oe_hse_advanced_jsa_template_trade",
            "oe_hse_advanced_jsa_template",
        ),
    ):
        if _has_index(inspector, table, name):
            try:
                op.drop_index(name, table_name=table)
            except sa.exc.OperationalError:
                pass

    # Drop added columns
    for table, col in (
        ("oe_hse_advanced_capa", "effectiveness_verified_by"),
        ("oe_hse_advanced_capa", "effectiveness_verified_at"),
        ("oe_hse_advanced_capa", "five_whys"),
        ("oe_hse_advanced_ptw", "prereq_atmospheric_test_passed"),
        ("oe_hse_advanced_ptw", "prereq_extinguisher_present"),
        ("oe_hse_advanced_ptw", "prereq_fire_watch_assigned"),
        ("oe_hse_advanced_ptw", "prereq_supervisor_present"),
        ("oe_hse_advanced_ptw", "prereq_jsa_approved"),
    ):
        if _has_column(inspector, table, col):
            with op.batch_alter_table(table) as batch:
                batch.drop_column(col)

    # Drop new tables
    for table in (
        "oe_hse_advanced_jsa_template",
        "oe_qms_calibration",
        "oe_qms_itp_template",
    ):
        if _has_table(inspector, table):
            op.drop_table(table)
