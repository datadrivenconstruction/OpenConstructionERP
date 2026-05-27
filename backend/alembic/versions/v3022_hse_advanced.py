# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""hse_advanced — JSA, PTW, toolbox talks, PPE, audits, CAPA, certifications.

Creates the eleven ``oe_hse_advanced_*`` tables backing the HSE Advanced
module: incident investigations, JSAs, permits-to-work, toolbox topic
library, toolbox talks + attendance, PPE issues, safety audits + findings,
CAPAs (corrective + preventive actions), and worker safety certifications.

Idempotent — re-applying on a DB where ``Base.metadata.create_all`` has
already created the tables is a no-op. Index creation is wrapped in
``try/except sa.exc.OperationalError`` to survive races and partial
inspector views.

Revision ID: v3022_hse_advanced
Revises: v3017_carbon
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3022_hse_advanced"
down_revision: Union[str, Sequence[str], None] = "v3021_schedule_advanced"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLES: tuple[str, ...] = (
    "oe_hse_advanced_incident_investigation",
    "oe_hse_advanced_toolbox_topic",
    "oe_hse_advanced_jsa",
    "oe_hse_advanced_ptw",
    "oe_hse_advanced_toolbox_talk",
    "oe_hse_advanced_toolbox_attendance",
    "oe_hse_advanced_ppe_issue",
    "oe_hse_advanced_audit",
    "oe_hse_advanced_capa",
    "oe_hse_advanced_audit_finding",
    "oe_hse_advanced_certification",
)


# (table, name, cols, unique)
_INDEXES: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    (
        "oe_hse_advanced_incident_investigation",
        "ix_oe_hse_advanced_incident_investigation_incident_ref",
        ("incident_ref",),
        False,
    ),
    (
        "oe_hse_advanced_incident_investigation",
        "ix_oe_hse_advanced_incident_investigation_status",
        ("status",),
        False,
    ),
    (
        "oe_hse_advanced_jsa",
        "ix_oe_hse_advanced_jsa_project_id",
        ("project_id",),
        False,
    ),
    (
        "oe_hse_advanced_jsa",
        "ix_oe_hse_advanced_jsa_status",
        ("status",),
        False,
    ),
    (
        "oe_hse_advanced_ptw",
        "ix_oe_hse_advanced_ptw_project_id",
        ("project_id",),
        False,
    ),
    (
        "oe_hse_advanced_ptw",
        "ix_oe_hse_advanced_ptw_permit_type",
        ("permit_type",),
        False,
    ),
    (
        "oe_hse_advanced_ptw",
        "ix_oe_hse_advanced_ptw_status",
        ("status",),
        False,
    ),
    (
        "oe_hse_advanced_toolbox_topic",
        "ix_oe_hse_advanced_toolbox_topic_code",
        ("code",),
        True,
    ),
    (
        "oe_hse_advanced_toolbox_topic",
        "ix_oe_hse_advanced_toolbox_topic_category",
        ("category",),
        False,
    ),
    (
        "oe_hse_advanced_toolbox_talk",
        "ix_oe_hse_advanced_toolbox_talk_project_id",
        ("project_id",),
        False,
    ),
    (
        "oe_hse_advanced_toolbox_talk",
        "ix_oe_hse_advanced_toolbox_talk_conducted_at",
        ("conducted_at",),
        False,
    ),
    (
        "oe_hse_advanced_toolbox_attendance",
        "ix_oe_hse_advanced_toolbox_attendance_talk_id",
        ("toolbox_talk_id",),
        False,
    ),
    (
        "oe_hse_advanced_ppe_issue",
        "ix_oe_hse_advanced_ppe_issue_ppe_type",
        ("ppe_type",),
        False,
    ),
    (
        "oe_hse_advanced_ppe_issue",
        "ix_oe_hse_advanced_ppe_issue_status",
        ("status",),
        False,
    ),
    (
        "oe_hse_advanced_audit",
        "ix_oe_hse_advanced_audit_project_id",
        ("project_id",),
        False,
    ),
    (
        "oe_hse_advanced_audit",
        "ix_oe_hse_advanced_audit_conducted_at",
        ("conducted_at",),
        False,
    ),
    (
        "oe_hse_advanced_audit",
        "ix_oe_hse_advanced_audit_status",
        ("status",),
        False,
    ),
    (
        "oe_hse_advanced_audit_finding",
        "ix_oe_hse_advanced_audit_finding_audit_id",
        ("audit_id",),
        False,
    ),
    (
        "oe_hse_advanced_audit_finding",
        "ix_oe_hse_advanced_audit_finding_category",
        ("category",),
        False,
    ),
    (
        "oe_hse_advanced_capa",
        "ix_oe_hse_advanced_capa_project_id",
        ("project_id",),
        False,
    ),
    (
        "oe_hse_advanced_capa",
        "ix_oe_hse_advanced_capa_source_type",
        ("source_type",),
        False,
    ),
    (
        "oe_hse_advanced_capa",
        "ix_oe_hse_advanced_capa_status",
        ("status",),
        False,
    ),
    (
        "oe_hse_advanced_certification",
        "ix_oe_hse_advanced_certification_cert_type",
        ("cert_type",),
        False,
    ),
    (
        "oe_hse_advanced_certification",
        "ix_oe_hse_advanced_certification_valid_until",
        ("valid_until",),
        False,
    ),
    (
        "oe_hse_advanced_certification",
        "ix_oe_hse_advanced_certification_status",
        ("status",),
        False,
    ),
)


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


def _audit_columns() -> list[sa.Column]:
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


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    # ── Incident investigation ──────────────────────────────────────────
    if not _has_table(inspector, "oe_hse_advanced_incident_investigation"):
        op.create_table(
            "oe_hse_advanced_incident_investigation",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column("incident_ref", guid, nullable=False),
            sa.Column(
                "investigation_lead",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "method",
                sa.String(50),
                nullable=False,
                server_default="5_whys",
            ),
            sa.Column("findings", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "recommendations",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "status",
                sa.String(50),
                nullable=False,
                server_default="in_progress",
            ),
            sa.Column("report_url", sa.String(1000), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )

    # ── Toolbox topic catalogue (referenced before JSA/PTW/talks; safe order) ──
    if not _has_table(inspector, "oe_hse_advanced_toolbox_topic"):
        op.create_table(
            "oe_hse_advanced_toolbox_topic",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "category",
                sa.String(50),
                nullable=False,
                server_default="general",
            ),
            sa.Column(
                "language",
                sa.String(10),
                nullable=False,
                server_default="en",
            ),
            sa.Column(
                "duration_minutes",
                sa.Integer(),
                nullable=False,
                server_default="5",
            ),
            sa.Column(
                "version",
                sa.String(20),
                nullable=False,
                server_default="1.0",
            ),
            sa.Column(
                "is_active",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1") if is_sqlite else sa.text("true"),
            ),
        )

    # ── JSA ──────────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_hse_advanced_jsa"):
        op.create_table(
            "oe_hse_advanced_jsa",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("task_description", sa.Text(), nullable=False),
            sa.Column("location", sa.String(500), nullable=True),
            sa.Column("work_date", sa.String(20), nullable=False),
            sa.Column(
                "prepared_by",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "approved_by",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "status",
                sa.String(50),
                nullable=False,
                server_default="draft",
            ),
            sa.Column(
                "hazards",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "required_ppe",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "risk_score",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("created_by", sa.String(36), nullable=True),
        )

    # ── PTW ──────────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_hse_advanced_ptw"):
        op.create_table(
            "oe_hse_advanced_ptw",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("permit_number", sa.String(50), nullable=False),
            sa.Column("permit_type", sa.String(50), nullable=False),
            sa.Column(
                "description",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column("location", sa.String(500), nullable=True),
            sa.Column("work_start", sa.DateTime(timezone=True), nullable=False),
            sa.Column("work_end", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "applicant_id",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "supervisor_id",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "jsa_id",
                guid,
                sa.ForeignKey("oe_hse_advanced_jsa.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "status",
                sa.String(50),
                nullable=False,
                server_default="requested",
            ),
            sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "approved_by",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "conditions",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "closure_checklist_passed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0") if is_sqlite else sa.text("false"),
            ),
            sa.Column(
                "closure_notes",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column("created_by", sa.String(36), nullable=True),
        )

    # ── Toolbox talk ─────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_hse_advanced_toolbox_talk"):
        op.create_table(
            "oe_hse_advanced_toolbox_talk",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("topic_code", sa.String(50), nullable=False),
            sa.Column("topic_title", sa.String(500), nullable=False),
            sa.Column("conducted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "conducted_by",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "language",
                sa.String(10),
                nullable=False,
                server_default="en",
            ),
            sa.Column(
                "attendance_count",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("library_topic_ref", guid, nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )

    # ── Toolbox attendance ───────────────────────────────────────────────
    if not _has_table(inspector, "oe_hse_advanced_toolbox_attendance"):
        op.create_table(
            "oe_hse_advanced_toolbox_attendance",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "toolbox_talk_id",
                guid,
                sa.ForeignKey(
                    "oe_hse_advanced_toolbox_talk.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("attendee_name", sa.String(255), nullable=False),
            sa.Column("attendee_company", sa.String(255), nullable=True),
            sa.Column(
                "attendee_role",
                sa.String(50),
                nullable=False,
                server_default="worker",
            ),
            sa.Column("signature_ref", sa.String(500), nullable=True),
            sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "attendance_status",
                sa.String(50),
                nullable=False,
                server_default="present",
            ),
        )

    # ── PPE issue ────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_hse_advanced_ppe_issue"):
        op.create_table(
            "oe_hse_advanced_ppe_issue",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "recipient_user_id",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("recipient_name", sa.String(255), nullable=True),
            sa.Column("recipient_company", sa.String(255), nullable=True),
            sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "issued_by",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("ppe_type", sa.String(50), nullable=False),
            sa.Column("size", sa.String(50), nullable=True),
            sa.Column("brand", sa.String(100), nullable=True),
            sa.Column("serial", sa.String(100), nullable=True),
            sa.Column("valid_until", sa.Date(), nullable=True),
            sa.Column("returned_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "status",
                sa.String(50),
                nullable=False,
                server_default="issued",
            ),
        )

    # ── Safety audit ─────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_hse_advanced_audit"):
        op.create_table(
            "oe_hse_advanced_audit",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "audit_type",
                sa.String(50),
                nullable=False,
                server_default="internal",
            ),
            sa.Column("conducted_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "conducted_by",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("score_total", sa.Numeric(5, 2), nullable=True),
            sa.Column("max_score", sa.Numeric(5, 2), nullable=True),
            sa.Column(
                "status",
                sa.String(50),
                nullable=False,
                server_default="scheduled",
            ),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("checklist_template_ref", guid, nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )

    # ── CAPA (created before audit_finding because finding.corrective_action_ref FK) ──
    if not _has_table(inspector, "oe_hse_advanced_capa"):
        op.create_table(
            "oe_hse_advanced_capa",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "project_id",
                guid,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source_type", sa.String(50), nullable=False),
            sa.Column("source_ref", guid, nullable=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column(
                "description",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "owner_user_id",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("target_date", sa.Date(), nullable=False),
            sa.Column(
                "status",
                sa.String(50),
                nullable=False,
                server_default="open",
            ),
            sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "verification_notes",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column("root_cause_category", sa.String(50), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )

    # ── Audit finding ────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_hse_advanced_audit_finding"):
        op.create_table(
            "oe_hse_advanced_audit_finding",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "audit_id",
                guid,
                sa.ForeignKey("oe_hse_advanced_audit.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("item_description", sa.Text(), nullable=False),
            sa.Column(
                "category",
                sa.String(50),
                nullable=False,
                server_default="other",
            ),
            sa.Column(
                "severity",
                sa.String(20),
                nullable=False,
                server_default="low",
            ),
            sa.Column(
                "is_passed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1") if is_sqlite else sa.text("true"),
            ),
            sa.Column("evidence_url", sa.String(1000), nullable=True),
            sa.Column(
                "corrective_action_ref",
                guid,
                sa.ForeignKey("oe_hse_advanced_capa.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    # ── Safety certification ─────────────────────────────────────────────
    if not _has_table(inspector, "oe_hse_advanced_certification"):
        op.create_table(
            "oe_hse_advanced_certification",
            sa.Column("id", guid, primary_key=True),
            *_audit_columns(),
            sa.Column(
                "owner_user_id",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("owner_name", sa.String(255), nullable=True),
            sa.Column("owner_company", sa.String(255), nullable=True),
            sa.Column("cert_type", sa.String(100), nullable=False),
            sa.Column("issued_by", sa.String(255), nullable=True),
            sa.Column("issue_date", sa.Date(), nullable=False),
            sa.Column("valid_until", sa.Date(), nullable=False),
            sa.Column("document_url", sa.String(1000), nullable=True),
            sa.Column(
                "status",
                sa.String(50),
                nullable=False,
                server_default="valid",
            ),
        )

    # Inspector cache is stale after CREATE TABLE.
    inspector = sa.inspect(bind)
    for table, name, cols, unique in _INDEXES:
        if _has_index(inspector, table, name):
            continue
        try:
            op.create_index(name, table, list(cols), unique=unique)
        except sa.exc.OperationalError:
            # Index race / already exists under a different inspector view.
            pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, name, _cols, _unique in _INDEXES:
        if _has_index(inspector, table, name):
            try:
                op.drop_index(name, table_name=table)
            except sa.exc.OperationalError:
                continue

    # Drop in reverse-dependency order:
    #   certification → audit_finding → capa → audit → ppe_issue →
    #   toolbox_attendance → toolbox_talk → ptw → jsa → toolbox_topic →
    #   incident_investigation.
    drop_order: tuple[str, ...] = (
        "oe_hse_advanced_certification",
        "oe_hse_advanced_audit_finding",
        "oe_hse_advanced_capa",
        "oe_hse_advanced_audit",
        "oe_hse_advanced_ppe_issue",
        "oe_hse_advanced_toolbox_attendance",
        "oe_hse_advanced_toolbox_talk",
        "oe_hse_advanced_ptw",
        "oe_hse_advanced_jsa",
        "oe_hse_advanced_toolbox_topic",
        "oe_hse_advanced_incident_investigation",
    )
    for table in drop_order:
        if _has_table(inspector, table):
            op.drop_table(table)
