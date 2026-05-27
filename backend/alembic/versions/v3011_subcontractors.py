# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""subcontractors — full lifecycle tables for Module 4.

Adds the 10 tables behind the Subcontractor Management module:

    oe_subcontractors_subcontractor
    oe_subcontractors_subcontractor_contact
    oe_subcontractors_prequalification
    oe_subcontractors_certificate
    oe_subcontractors_agreement
    oe_subcontractors_work_package
    oe_subcontractors_payment_application
    oe_subcontractors_payment_application_line
    oe_subcontractors_retention_ledger
    oe_subcontractors_rating

Idempotent — re-applying on a DB where ``Base.metadata.create_all`` has
already created the tables is a no-op. Indexes are added in a second pass
after CREATE TABLE so the inspector cache reflects them.

Revision ID: v3011_subcontractors
Revises: v2943_compliance_docs
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3011_subcontractors"
down_revision: Union[str, Sequence[str], None] = "v3010_service"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_TABLE_SUBCONTRACTOR = "oe_subcontractors_subcontractor"
_TABLE_CONTACT = "oe_subcontractors_subcontractor_contact"
_TABLE_PREQUAL = "oe_subcontractors_prequalification"
_TABLE_CERT = "oe_subcontractors_certificate"
_TABLE_AGREEMENT = "oe_subcontractors_agreement"
_TABLE_WP = "oe_subcontractors_work_package"
_TABLE_PA = "oe_subcontractors_payment_application"
_TABLE_PA_LINE = "oe_subcontractors_payment_application_line"
_TABLE_RETENTION = "oe_subcontractors_retention_ledger"
_TABLE_RATING = "oe_subcontractors_rating"

_INDEXES: tuple[tuple[str, str, tuple[str, ...], bool], ...] = (
    # (index_name, table_name, columns, unique)
    ("ix_oe_subcontractors_subcontractor_contact_id", _TABLE_SUBCONTRACTOR, ("contact_id",), False),
    ("ix_oe_subcontractors_subcontractor_tax_id", _TABLE_SUBCONTRACTOR, ("tax_id",), False),
    (
        "ix_oe_subcontractors_subcontractor_prequalification_status",
        _TABLE_SUBCONTRACTOR,
        ("prequalification_status",),
        False,
    ),
    (
        "ix_oe_subcontractors_subcontractor_contact_subcontractor_id",
        _TABLE_CONTACT,
        ("subcontractor_id",),
        False,
    ),
    (
        "ix_oe_subcontractors_prequalification_subcontractor_id",
        _TABLE_PREQUAL,
        ("subcontractor_id",),
        False,
    ),
    (
        "ix_oe_subcontractors_prequalification_status",
        _TABLE_PREQUAL,
        ("status",),
        False,
    ),
    (
        "ix_oe_subcontractors_certificate_subcontractor_id",
        _TABLE_CERT,
        ("subcontractor_id",),
        False,
    ),
    ("ix_oe_subcontractors_certificate_cert_type", _TABLE_CERT, ("cert_type",), False),
    (
        "ix_oe_subcontractors_certificate_valid_until",
        _TABLE_CERT,
        ("valid_until",),
        False,
    ),
    ("ix_oe_subcontractors_certificate_status", _TABLE_CERT, ("status",), False),
    (
        "ix_oe_subcontractors_agreement_subcontractor_id",
        _TABLE_AGREEMENT,
        ("subcontractor_id",),
        False,
    ),
    (
        "ix_oe_subcontractors_agreement_project_id",
        _TABLE_AGREEMENT,
        ("project_id",),
        False,
    ),
    ("ix_oe_subcontractors_agreement_status", _TABLE_AGREEMENT, ("status",), False),
    (
        "ix_oe_subcontractors_work_package_agreement_id",
        _TABLE_WP,
        ("agreement_id",),
        False,
    ),
    ("ix_oe_subcontractors_work_package_status", _TABLE_WP, ("status",), False),
    (
        "ix_oe_subcontractors_payment_application_agreement_id",
        _TABLE_PA,
        ("agreement_id",),
        False,
    ),
    (
        "ix_oe_subcontractors_payment_application_status",
        _TABLE_PA,
        ("status",),
        False,
    ),
    (
        "ix_oe_subcontractors_payment_application_line_payment_application_id",
        _TABLE_PA_LINE,
        ("payment_application_id",),
        False,
    ),
    (
        "ix_oe_subcontractors_payment_application_line_work_package_id",
        _TABLE_PA_LINE,
        ("work_package_id",),
        False,
    ),
    (
        "ix_oe_subcontractors_retention_ledger_agreement_id",
        _TABLE_RETENTION,
        ("agreement_id",),
        False,
    ),
    (
        "ix_oe_subcontractors_retention_ledger_payment_application_id",
        _TABLE_RETENTION,
        ("payment_application_id",),
        False,
    ),
    (
        "ix_oe_subcontractors_rating_subcontractor_id",
        _TABLE_RATING,
        ("subcontractor_id",),
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


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    if not _has_table(inspector, _TABLE_SUBCONTRACTOR):
        op.create_table(
            _TABLE_SUBCONTRACTOR,
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
            sa.Column(
                "contact_id",
                guid_type,
                sa.ForeignKey("oe_contacts_contact.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("legal_name", sa.String(255), nullable=False),
            sa.Column("trade_name", sa.String(255), nullable=True),
            sa.Column("tax_id", sa.String(64), nullable=True),
            sa.Column("trade_categories", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column(
                "prequalification_status",
                sa.String(32),
                nullable=False,
                server_default="pending",
            ),
            sa.Column("rating_score", sa.Numeric(5, 2), nullable=False, server_default="0"),
            sa.Column("country", sa.String(2), nullable=True),
            sa.Column("address", sa.JSON(), nullable=True),
            sa.Column("website", sa.String(500), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    if not _has_table(inspector, _TABLE_CONTACT):
        op.create_table(
            _TABLE_CONTACT,
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
            sa.Column(
                "subcontractor_id",
                guid_type,
                sa.ForeignKey(
                    f"{_TABLE_SUBCONTRACTOR}.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("role", sa.String(120), nullable=True),
            sa.Column("email", sa.String(255), nullable=True),
            sa.Column("phone", sa.String(64), nullable=True),
            sa.Column(
                "primary",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )

    if not _has_table(inspector, _TABLE_PREQUAL):
        op.create_table(
            _TABLE_PREQUAL,
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
            sa.Column(
                "subcontractor_id",
                guid_type,
                sa.ForeignKey(
                    f"{_TABLE_SUBCONTRACTOR}.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("answers", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("reviewer_id", sa.String(36), nullable=True),
            sa.Column("decision_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
        )

    if not _has_table(inspector, _TABLE_CERT):
        op.create_table(
            _TABLE_CERT,
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
            sa.Column(
                "subcontractor_id",
                guid_type,
                sa.ForeignKey(
                    f"{_TABLE_SUBCONTRACTOR}.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("cert_type", sa.String(32), nullable=False),
            sa.Column("issued_by", sa.String(255), nullable=True),
            sa.Column("issue_date", sa.Date(), nullable=True),
            sa.Column("valid_until", sa.Date(), nullable=True),
            sa.Column("document_url", sa.String(1000), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="valid"),
            sa.Column(
                "revoked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    if not _has_table(inspector, _TABLE_AGREEMENT):
        op.create_table(
            _TABLE_AGREEMENT,
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
            sa.Column(
                "subcontractor_id",
                guid_type,
                sa.ForeignKey(
                    f"{_TABLE_SUBCONTRACTOR}.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("total_value", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("start_date", sa.Date(), nullable=True),
            sa.Column("end_date", sa.Date(), nullable=True),
            sa.Column(
                "retention_percent",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="5.0",
            ),
            sa.Column("retention_release_event", sa.String(120), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    if not _has_table(inspector, _TABLE_WP):
        op.create_table(
            _TABLE_WP,
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
            sa.Column(
                "agreement_id",
                guid_type,
                sa.ForeignKey(f"{_TABLE_AGREEMENT}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("name", sa.String(500), nullable=False),
            sa.Column("scope", sa.Text(), nullable=True),
            sa.Column(
                "planned_value",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "completion_percent",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("status", sa.String(32), nullable=False, server_default="planned"),
        )

    if not _has_table(inspector, _TABLE_PA):
        op.create_table(
            _TABLE_PA,
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
            sa.Column(
                "agreement_id",
                guid_type,
                sa.ForeignKey(f"{_TABLE_AGREEMENT}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("application_number", sa.String(40), nullable=False),
            sa.Column("period_start", sa.Date(), nullable=True),
            sa.Column("period_end", sa.Date(), nullable=True),
            sa.Column(
                "gross_amount",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "retention_amount",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "net_amount",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="submitted",
            ),
            sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("foreman_approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("foreman_approved_by", sa.String(36), nullable=True),
            sa.Column("finance_approved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("finance_approved_by", sa.String(36), nullable=True),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("rejection_reason", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    if not _has_table(inspector, _TABLE_PA_LINE):
        op.create_table(
            _TABLE_PA_LINE,
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
            sa.Column(
                "payment_application_id",
                guid_type,
                sa.ForeignKey(f"{_TABLE_PA}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "work_package_id",
                guid_type,
                sa.ForeignKey(f"{_TABLE_WP}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "claimed_amount",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "certified_amount",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "approved_amount",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
        )

    if not _has_table(inspector, _TABLE_RETENTION):
        op.create_table(
            _TABLE_RETENTION,
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
            sa.Column(
                "agreement_id",
                guid_type,
                sa.ForeignKey(f"{_TABLE_AGREEMENT}.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "payment_application_id",
                guid_type,
                sa.ForeignKey(f"{_TABLE_PA}.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "accrued_amount",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "released_amount",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("release_reason", sa.String(255), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
        )

    if not _has_table(inspector, _TABLE_RATING):
        op.create_table(
            _TABLE_RATING,
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
            sa.Column(
                "subcontractor_id",
                guid_type,
                sa.ForeignKey(
                    f"{_TABLE_SUBCONTRACTOR}.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("period", sa.String(7), nullable=False),
            sa.Column(
                "quality_score",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "hse_score",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "schedule_score",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "cost_score",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "overall_score",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("basis", sa.JSON(), nullable=False, server_default="{}"),
        )

    inspector = sa.inspect(bind)
    for name, table, cols, unique in _INDEXES:
        if not _has_index(inspector, table, name):
            try:
                op.create_index(name, table, list(cols), unique=unique)
            except sa.exc.OperationalError:
                pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for name, table, _cols, _unique in _INDEXES:
        if _has_index(inspector, table, name):
            op.drop_index(name, table_name=table)

    for table in (
        _TABLE_RATING,
        _TABLE_RETENTION,
        _TABLE_PA_LINE,
        _TABLE_PA,
        _TABLE_WP,
        _TABLE_AGREEMENT,
        _TABLE_CERT,
        _TABLE_PREQUAL,
        _TABLE_CONTACT,
        _TABLE_SUBCONTRACTOR,
    ):
        if _has_table(inspector, table):
            op.drop_table(table)
