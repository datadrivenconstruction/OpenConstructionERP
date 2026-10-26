# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""field evidence, handover dossier, condition rating and maintenance plan.

Additive only, no data rewrite:

* ``oe_dlp_defect``: nullable photo evidence list and WGS84 pin (``photos``,
  ``geo_lat``, ``geo_lon``);
* new tables ``oe_closeout_dossier`` and ``oe_closeout_delivery``: an assembled
  handover dossier and its delivery log;
* new tables ``oe_condition_scale``, ``oe_condition_assessment`` and
  ``oe_condition_action``: project condition scales, condition ratings and the
  maintenance plan.

Punch item photo evidence rides the existing ``metadata`` JSON column and needs
no schema change. Every step is inspector-guarded, so a database whose tables
``create_all`` already built reaches this revision and does nothing.

Revision ID: v201_field_handover_condition
Revises: v200_supplier_pricelists_discounts
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v201_field_handover_condition"
down_revision: str | Sequence[str] | None = "v200_supplier_pricelists_discounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DEFECT = "oe_dlp_defect"
_DOSSIER = "oe_closeout_dossier"
_DELIVERY = "oe_closeout_delivery"
_SCALE = "oe_condition_scale"
_ASSESSMENT = "oe_condition_assessment"
_ACTION = "oe_condition_action"


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _meta() -> sa.Column:
    return sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}")


def upgrade() -> None:
    """Add the defect evidence columns and create the five tables when missing."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())

    if _DEFECT in tables:
        have = {c["name"] for c in insp.get_columns(_DEFECT)}
        if "photos" not in have:
            op.add_column(_DEFECT, sa.Column("photos", sa.JSON(), nullable=False, server_default="[]"))
        if "geo_lat" not in have:
            op.add_column(_DEFECT, sa.Column("geo_lat", sa.Float(), nullable=True))
        if "geo_lon" not in have:
            op.add_column(_DEFECT, sa.Column("geo_lon", sa.Float(), nullable=True))

    if _DOSSIER not in tables and "oe_closeout_package" in tables:
        op.create_table(
            _DOSSIER,
            *_stamps(),
            sa.Column(
                "package_id", GUID(), sa.ForeignKey("oe_closeout_package.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
            sa.Column("scope", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("check_status", sa.String(20), nullable=True),
            sa.Column("check_results", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("delivery_request", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("job_id", GUID(), nullable=True),
            sa.Column("document_id", GUID(), nullable=True),
            sa.Column("file_path", sa.String(1024), nullable=True),
            sa.Column("file_name", sa.String(255), nullable=True),
            sa.Column("sha256", sa.String(64), nullable=True),
            sa.Column("size_bytes", sa.BigInteger(), nullable=True),
            sa.Column("file_count", sa.Integer(), nullable=True),
            sa.Column("built_at", sa.String(40), nullable=True),
            sa.Column("requested_by", sa.String(36), nullable=True),
            sa.Column("error", sa.Text(), nullable=True),
            _meta(),
        )
        op.create_index(f"ix_{_DOSSIER}_package_id", _DOSSIER, ["package_id"])
        op.create_index(f"ix_{_DOSSIER}_project_id", _DOSSIER, ["project_id"])
        op.create_index("ix_closeout_dossier_package_created", _DOSSIER, ["package_id", "created_at"])
        tables.add(_DOSSIER)

    if _DELIVERY not in tables and _DOSSIER in tables:
        op.create_table(
            _DELIVERY,
            *_stamps(),
            sa.Column("dossier_id", GUID(), sa.ForeignKey(f"{_DOSSIER}.id", ondelete="CASCADE"), nullable=False),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("channel", sa.String(20), nullable=False),
            sa.Column("target_id", sa.String(36), nullable=True),
            sa.Column("target_label", sa.String(255), nullable=True),
            sa.Column("recipient", sa.String(320), nullable=True),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("status_code", sa.Integer(), nullable=True),
            sa.Column("detail", sa.Text(), nullable=True),
            sa.Column("share_link_id", GUID(), nullable=True),
            sa.Column("share_url", sa.String(1024), nullable=True),
            sa.Column("share_expires_at", sa.String(40), nullable=True),
            sa.Column("resend_of", GUID(), nullable=True),
            sa.Column("delivered_by", sa.String(36), nullable=True),
            sa.Column("delivered_at", sa.String(40), nullable=True),
            _meta(),
        )
        op.create_index(f"ix_{_DELIVERY}_dossier_id", _DELIVERY, ["dossier_id"])
        op.create_index(f"ix_{_DELIVERY}_project_id", _DELIVERY, ["project_id"])
        op.create_index("ix_closeout_delivery_dossier_created", _DELIVERY, ["dossier_id", "created_at"])

    project_fk = sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE")
    if _SCALE not in tables:
        op.create_table(
            _SCALE,
            *_stamps(),
            sa.Column("project_id", GUID(), project_fk, nullable=False),
            sa.Column("key", sa.String(60), nullable=False),
            sa.Column("name", sa.String(120), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("action_threshold", sa.Integer(), nullable=False, server_default="4"),
            sa.Column("levels", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", "key", name="uq_condition_scale_project_key"),
        )
        op.create_index(f"ix_{_SCALE}_project_id", _SCALE, ["project_id"])

    if _ASSESSMENT not in tables:
        op.create_table(
            _ASSESSMENT,
            *_stamps(),
            sa.Column(
                "project_id", GUID(), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("inspection_id", sa.String(36), nullable=True),
            sa.Column("asset_kind", sa.String(20), nullable=False, server_default="element"),
            sa.Column("asset_ref", sa.String(100), nullable=True),
            sa.Column("element_name", sa.String(255), nullable=False),
            sa.Column("element_code", sa.String(60), nullable=True),
            sa.Column("area", sa.String(255), nullable=True),
            sa.Column("scale_key", sa.String(60), nullable=False, server_default="default_6"),
            sa.Column("rating", sa.Integer(), nullable=False),
            sa.Column("suggested_rating", sa.Integer(), nullable=True),
            sa.Column("suggestion_confidence", sa.Float(), nullable=True),
            sa.Column("severity", sa.Integer(), nullable=True),
            sa.Column("extent_pct", sa.Float(), nullable=True),
            sa.Column("intensity", sa.Integer(), nullable=True),
            sa.Column("defect_description", sa.Text(), nullable=True),
            sa.Column("recommended_action", sa.Text(), nullable=True),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
            sa.Column("unit", sa.String(20), nullable=True),
            sa.Column("unit_cost", sa.Numeric(18, 2), nullable=True),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("assessed_at", sa.Date(), nullable=True),
            sa.Column("assessed_by", sa.String(36), nullable=True),
            sa.Column("photos", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("notes", sa.Text(), nullable=True),
            _meta(),
        )
        op.create_index(f"ix_{_ASSESSMENT}_project_id", _ASSESSMENT, ["project_id"])
        op.create_index(f"ix_{_ASSESSMENT}_inspection_id", _ASSESSMENT, ["inspection_id"])
        op.create_index("ix_condition_assessment_project_asset", _ASSESSMENT, ["project_id", "asset_ref"])
        op.create_index("ix_condition_assessment_project_date", _ASSESSMENT, ["project_id", "assessed_at"])
        tables.add(_ASSESSMENT)

    if _ACTION not in tables:
        op.create_table(
            _ACTION,
            *_stamps(),
            sa.Column(
                "project_id", GUID(), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("assessment_id", GUID(), sa.ForeignKey(f"{_ASSESSMENT}.id", ondelete="SET NULL"), nullable=True),
            sa.Column("asset_kind", sa.String(20), nullable=False, server_default="element"),
            sa.Column("asset_ref", sa.String(100), nullable=True),
            sa.Column("element_name", sa.String(255), nullable=False),
            sa.Column("area", sa.String(255), nullable=True),
            sa.Column("action_type", sa.String(20), nullable=False),
            sa.Column("description", sa.String(500), nullable=False, server_default=""),
            sa.Column("first_year", sa.Integer(), nullable=False),
            sa.Column("interval_years", sa.Integer(), nullable=True),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
            sa.Column("unit", sa.String(20), nullable=True),
            sa.Column("unit_cost", sa.Numeric(18, 2), nullable=True),
            sa.Column("currency", sa.String(3), nullable=True),
            sa.Column("priority", sa.Integer(), nullable=False, server_default="3"),
            sa.Column("status", sa.String(20), nullable=False, server_default="proposed"),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("confidence", sa.Float(), nullable=True),
            sa.Column("decided_by", sa.String(36), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            _meta(),
        )
        op.create_index(f"ix_{_ACTION}_project_id", _ACTION, ["project_id"])
        op.create_index("ix_condition_action_project_status", _ACTION, ["project_id", "status"])
        op.create_index("ix_condition_action_assessment", _ACTION, ["assessment_id"])


def downgrade() -> None:
    """Drop the five tables and the defect evidence columns."""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for table in (_ACTION, _ASSESSMENT, _SCALE, _DELIVERY, _DOSSIER):
        if table in tables:
            op.drop_table(table)
    if _DEFECT in tables:
        have = {c["name"] for c in insp.get_columns(_DEFECT)}
        for column in ("geo_lon", "geo_lat", "photos"):
            if column in have:
                op.drop_column(_DEFECT, column)
