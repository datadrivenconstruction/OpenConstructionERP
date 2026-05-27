# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""qms — unified Quality Management System (ITP + Inspections + NCR + Punch + Audits).

Adds 9 tables prefixed ``oe_qms_`` plus indexes on hot-path columns
(``project_id``, ``status``, intra-module FKs). Idempotent — re-applying
on a DB where ``Base.metadata.create_all`` already created the tables
is a no-op. External FKs to ``oe_projects_project`` / ``oe_users_user``
are intentionally NOT declared at the ORM layer so minimal-model test
fixtures keep working; they ARE declared here in the migration where
the referenced tables exist in production.

Revision ID: v3024_qms
Revises: v2943_compliance_docs
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3024_qms"
down_revision: Union[str, Sequence[str], None] = "v3023_daily_diary"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ── Helpers ─────────────────────────────────────────────────────────


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    index: str,
) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def _safe_create_index(name: str, table: str, cols: list[str]) -> None:
    """Create an index, swallowing OperationalError (re-runs on prod DB)."""
    try:
        op.create_index(name, table, cols)
    except sa.exc.OperationalError:
        pass


# Table → list of (index_name, columns)
_INDEX_SPEC: dict[str, list[tuple[str, list[str]]]] = {
    "oe_qms_itp_plan": [
        ("ix_oe_qms_itp_plan_project_id", ["project_id"]),
        ("ix_oe_qms_itp_plan_status", ["status"]),
    ],
    "oe_qms_itp_item": [
        ("ix_oe_qms_itp_item_itp_plan_id", ["itp_plan_id"]),
    ],
    "oe_qms_inspection": [
        ("ix_oe_qms_inspection_project_id", ["project_id"]),
        ("ix_oe_qms_inspection_status", ["status"]),
        ("ix_oe_qms_inspection_itp_item_id", ["itp_item_id"]),
    ],
    "oe_qms_inspection_signature": [
        ("ix_oe_qms_inspection_signature_inspection_id", ["inspection_id"]),
    ],
    "oe_qms_ncr": [
        ("ix_oe_qms_ncr_project_id", ["project_id"]),
        ("ix_oe_qms_ncr_status", ["status"]),
        ("ix_oe_qms_ncr_severity", ["severity"]),
    ],
    "oe_qms_ncr_action": [
        ("ix_oe_qms_ncr_action_ncr_id", ["ncr_id"]),
        ("ix_oe_qms_ncr_action_status", ["status"]),
    ],
    "oe_qms_punch_item": [
        ("ix_oe_qms_punch_item_project_id", ["project_id"]),
        ("ix_oe_qms_punch_item_status", ["status"]),
    ],
    "oe_qms_audit": [
        ("ix_oe_qms_audit_project_id", ["project_id"]),
        ("ix_oe_qms_audit_status", ["status"]),
    ],
    "oe_qms_audit_finding": [
        ("ix_oe_qms_audit_finding_audit_id", ["audit_id"]),
        ("ix_oe_qms_audit_finding_status", ["status"]),
    ],
}


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

    # 1) oe_qms_itp_plan
    if not _has_table(inspector, "oe_qms_itp_plan"):
        op.create_table(
            "oe_qms_itp_plan",
            *_id_cols(),
            sa.Column("project_id", guid_type, nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("work_type", sa.String(100), nullable=False),
            sa.Column("wbs_ref", sa.String(100), nullable=True),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="draft",
            ),
            sa.Column(
                "version",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column("created_by", sa.String(36), nullable=True),
        )

    # 2) oe_qms_itp_item
    if not _has_table(inspector, "oe_qms_itp_item"):
        op.create_table(
            "oe_qms_itp_item",
            *_id_cols(),
            sa.Column(
                "itp_plan_id",
                guid_type,
                sa.ForeignKey("oe_qms_itp_plan.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "sequence",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("control_point_name", sa.String(255), nullable=False),
            sa.Column("criteria", sa.Text(), nullable=True),
            sa.Column("frequency", sa.String(100), nullable=True),
            sa.Column("method", sa.String(100), nullable=True),
            sa.Column("acceptance_criteria", sa.Text(), nullable=True),
            sa.Column(
                "hold_witness_point",
                sa.String(16),
                nullable=False,
                server_default="review",
            ),
            sa.Column("responsible_role", sa.String(100), nullable=True),
            sa.Column(
                "signatories_required",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
        )

    # 3) oe_qms_inspection
    if not _has_table(inspector, "oe_qms_inspection"):
        op.create_table(
            "oe_qms_inspection",
            *_id_cols(),
            sa.Column(
                "itp_item_id",
                guid_type,
                sa.ForeignKey("oe_qms_itp_item.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("project_id", guid_type, nullable=False),
            sa.Column("location_ref", sa.String(255), nullable=True),
            sa.Column("inspector_user_id", guid_type, nullable=True),
            sa.Column("scheduled_at", sa.String(32), nullable=True),
            sa.Column("performed_at", sa.String(32), nullable=True),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="scheduled",
            ),
            sa.Column("bim_element_ref", sa.String(255), nullable=True),
            sa.Column("drawing_ref", sa.String(255), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "photos_json",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )

    # 4) oe_qms_inspection_signature
    if not _has_table(inspector, "oe_qms_inspection_signature"):
        op.create_table(
            "oe_qms_inspection_signature",
            *_id_cols(),
            sa.Column(
                "inspection_id",
                guid_type,
                sa.ForeignKey("oe_qms_inspection.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("signer_user_id", guid_type, nullable=False),
            sa.Column("signer_role", sa.String(64), nullable=False),
            sa.Column("signed_at", sa.String(32), nullable=True),
            sa.Column(
                "signature_method",
                sa.String(32),
                nullable=False,
                server_default="electronic",
            ),
            sa.Column("comments", sa.Text(), nullable=True),
        )

    # 5) oe_qms_ncr
    if not _has_table(inspector, "oe_qms_ncr"):
        op.create_table(
            "oe_qms_ncr",
            *_id_cols(),
            sa.Column("project_id", guid_type, nullable=False),
            sa.Column("raised_by", guid_type, nullable=True),
            sa.Column("raised_at", sa.String(32), nullable=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column(
                "severity",
                sa.String(16),
                nullable=False,
                server_default="minor",
            ),
            sa.Column("root_cause", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="open",
            ),
            sa.Column(
                "cost_impact_currency",
                sa.String(3),
                nullable=False,
                server_default="",
            ),
            sa.Column("cost_impact_amount", sa.Numeric(15, 2), nullable=True),
            sa.Column("linked_variation_id", guid_type, nullable=True),
            sa.Column("linked_inspection_id", guid_type, nullable=True),
        )

    # 6) oe_qms_ncr_action
    if not _has_table(inspector, "oe_qms_ncr_action"):
        op.create_table(
            "oe_qms_ncr_action",
            *_id_cols(),
            sa.Column(
                "ncr_id",
                guid_type,
                sa.ForeignKey("oe_qms_ncr.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("responsible_user_id", guid_type, nullable=True),
            sa.Column("due_date", sa.String(32), nullable=True),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="assigned",
            ),
            sa.Column("verification_method", sa.String(255), nullable=True),
            sa.Column("verified_by", guid_type, nullable=True),
            sa.Column("verified_at", sa.String(32), nullable=True),
            sa.Column("completed_at", sa.String(32), nullable=True),
        )

    # 7) oe_qms_punch_item
    if not _has_table(inspector, "oe_qms_punch_item"):
        op.create_table(
            "oe_qms_punch_item",
            *_id_cols(),
            sa.Column("project_id", guid_type, nullable=False),
            sa.Column("raised_at", sa.String(32), nullable=True),
            sa.Column("raised_by", guid_type, nullable=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column("room_ref", sa.String(255), nullable=True),
            sa.Column("drawing_ref", sa.String(255), nullable=True),
            sa.Column("bim_element_ref", sa.String(255), nullable=True),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="open",
            ),
            sa.Column(
                "severity",
                sa.String(16),
                nullable=False,
                server_default="minor",
            ),
            sa.Column("assigned_to", guid_type, nullable=True),
            sa.Column("due_date", sa.String(32), nullable=True),
            sa.Column("closed_at", sa.String(32), nullable=True),
            sa.Column(
                "photos_json",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "source",
                sa.String(32),
                nullable=False,
                server_default="manual",
            ),
            sa.Column("category", sa.String(64), nullable=True),
        )

    # 8) oe_qms_audit
    if not _has_table(inspector, "oe_qms_audit"):
        op.create_table(
            "oe_qms_audit",
            *_id_cols(),
            sa.Column("project_id", guid_type, nullable=False),
            sa.Column(
                "audit_type",
                sa.String(32),
                nullable=False,
                server_default="internal",
            ),
            sa.Column("planned_date", sa.String(32), nullable=True),
            sa.Column("performed_at", sa.String(32), nullable=True),
            sa.Column("auditor_user_id", guid_type, nullable=True),
            sa.Column("audit_scope", sa.Text(), nullable=True),
            sa.Column("standard_ref", sa.String(64), nullable=True),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="planned",
            ),
            sa.Column("overall_rating", sa.Integer(), nullable=True),
        )

    # 9) oe_qms_audit_finding
    if not _has_table(inspector, "oe_qms_audit_finding"):
        op.create_table(
            "oe_qms_audit_finding",
            *_id_cols(),
            sa.Column(
                "audit_id",
                guid_type,
                sa.ForeignKey("oe_qms_audit.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "finding_type",
                sa.String(32),
                nullable=False,
                server_default="observation",
            ),
            sa.Column("description", sa.Text(), nullable=False),
            sa.Column("clause_ref", sa.String(64), nullable=True),
            sa.Column("corrective_action_required", sa.Text(), nullable=True),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="open",
            ),
            sa.Column("due_date", sa.String(32), nullable=True),
            sa.Column("closed_at", sa.String(32), nullable=True),
        )

    # Inspector cache is stale after CREATE TABLE.
    inspector = sa.inspect(bind)
    for table, idx_list in _INDEX_SPEC.items():
        for idx_name, cols in idx_list:
            if not _has_index(inspector, table, idx_name):
                _safe_create_index(idx_name, table, cols)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop indexes first
    for table, idx_list in _INDEX_SPEC.items():
        for idx_name, _cols in idx_list:
            if _has_index(inspector, table, idx_name):
                try:
                    op.drop_index(idx_name, table_name=table)
                except sa.exc.OperationalError:
                    pass

    # Drop tables in reverse-dependency order
    for table in (
        "oe_qms_audit_finding",
        "oe_qms_audit",
        "oe_qms_punch_item",
        "oe_qms_ncr_action",
        "oe_qms_ncr",
        "oe_qms_inspection_signature",
        "oe_qms_inspection",
        "oe_qms_itp_item",
        "oe_qms_itp_plan",
    ):
        if _has_table(inspector, table):
            op.drop_table(table)
