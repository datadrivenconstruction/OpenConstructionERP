# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""bid_management — bid packages, invitations, Q&A, leveling, award workflow.

Adds 11 ``oe_bid_management_*`` tables for the sister-to-tendering Bid
Management module. All cross-module references (tender_id, bidder_ref_id,
contract_template_ref) are plain UUID/string columns — no FK constraints
crossing module boundaries.

Idempotent — re-applying on a DB that already has the tables created via
``Base.metadata.create_all`` is a no-op.

Revision ID: v3019_bid_management
Revises: v3017_carbon
Create Date: 2026-05-12
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3019_bid_management"
down_revision: Union[str, Sequence[str], None] = "v3018_property_dev"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, [(col, type, kwargs)], [(index_name, cols, unique)])
_TABLES: tuple = (
    "oe_bid_management_package",
    "oe_bid_management_line_item",
    "oe_bid_management_invitation",
    "oe_bid_management_bidder",
    "oe_bid_management_submission",
    "oe_bid_management_submission_line",
    "oe_bid_management_qa",
    "oe_bid_management_comparison",
    "oe_bid_management_leveling",
    "oe_bid_management_award",
    "oe_bid_management_rejection",
)


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, index: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def _safe_create_index(
    inspector: sa.engine.reflection.Inspector,
    name: str,
    table: str,
    cols: list[str],
    *,
    unique: bool = False,
) -> None:
    """Create an index only if it doesn't already exist.

    Wrapped in try/except OperationalError so a race with another
    migration tool (e.g. an alembic-out-of-band create_all that already
    laid down the same index) doesn't blow up the migration.
    """
    if _has_index(inspector, table, name):
        return
    try:
        op.create_index(name, table, cols, unique=unique)
    except sa.exc.OperationalError:
        # Index materialised by a parallel actor — accept silently.
        pass


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    # ── oe_bid_management_package ───────────────────────────────────
    if not _has_table(inspector, "oe_bid_management_package"):
        op.create_table(
            "oe_bid_management_package",
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
                "project_id",
                guid_type,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            # tender_id is a PLAIN UUID — no FK to oe_tendering.
            sa.Column("tender_id", guid_type, nullable=True),
            sa.Column("code", sa.String(64), nullable=False),
            sa.Column("title", sa.String(500), nullable=False, server_default=""),
            sa.Column("scope_description", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "instructions_to_bidders",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column("submission_deadline", sa.String(40), nullable=True),
            sa.Column("decision_due_by", sa.String(40), nullable=True),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column(
                "total_budget_estimate",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
            sa.Column(
                "confidentiality_level",
                sa.String(32),
                nullable=False,
                server_default="limited",
            ),
            sa.Column("published_at", sa.String(40), nullable=True),
            sa.Column("closed_at", sa.String(40), nullable=True),
            sa.Column("awarded_at", sa.String(40), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("code", name="uq_oe_bid_management_package_code"),
        )

    inspector = sa.inspect(bind)
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_package_project_id",
        "oe_bid_management_package",
        ["project_id"],
    )
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_package_tender_id",
        "oe_bid_management_package",
        ["tender_id"],
    )
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_package_status",
        "oe_bid_management_package",
        ["status"],
    )

    # ── oe_bid_management_line_item ─────────────────────────────────
    if not _has_table(inspector, "oe_bid_management_line_item"):
        op.create_table(
            "oe_bid_management_line_item",
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
                "package_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("code", sa.String(64), nullable=False, server_default=""),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("unit", sa.String(20), nullable=False, server_default=""),
            sa.Column("quantity", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column(
                "alternative_allowed",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0") if is_sqlite else sa.text("false"),
            ),
            sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "parent_line_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_line_item.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("spec_attachment_url", sa.String(1024), nullable=True),
            sa.Column(
                "is_mandatory",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("1") if is_sqlite else sa.text("true"),
            ),
        )

    inspector = sa.inspect(bind)
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_line_item_package_id",
        "oe_bid_management_line_item",
        ["package_id"],
    )
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_line_item_parent_line_id",
        "oe_bid_management_line_item",
        ["parent_line_id"],
    )

    # ── oe_bid_management_invitation ────────────────────────────────
    if not _has_table(inspector, "oe_bid_management_invitation"):
        op.create_table(
            "oe_bid_management_invitation",
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
                "package_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
                nullable=False,
            ),
            # bidder_ref_id — plain UUID, no FK across modules
            sa.Column("bidder_ref_id", guid_type, nullable=True),
            sa.Column("invitee_email", sa.String(255), nullable=False, server_default=""),
            sa.Column(
                "invitee_company_name",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column("sent_at", sa.String(40), nullable=True),
            sa.Column("opened_at", sa.String(40), nullable=True),
            sa.Column("submission_received_at", sa.String(40), nullable=True),
            sa.Column("declined_at", sa.String(40), nullable=True),
            sa.Column("decline_reason", sa.Text(), nullable=True),
            sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
            sa.Column("token_hash", sa.String(64), nullable=True),
        )

    inspector = sa.inspect(bind)
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_invitation_package_id",
        "oe_bid_management_invitation",
        ["package_id"],
    )
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_invitation_bidder_ref_id",
        "oe_bid_management_invitation",
        ["bidder_ref_id"],
    )
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_invitation_status",
        "oe_bid_management_invitation",
        ["status"],
    )
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_invitation_token_hash",
        "oe_bid_management_invitation",
        ["token_hash"],
    )

    # ── oe_bid_management_bidder ────────────────────────────────────
    if not _has_table(inspector, "oe_bid_management_bidder"):
        op.create_table(
            "oe_bid_management_bidder",
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
                "package_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("company_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("contact_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("contact_email", sa.String(255), nullable=False, server_default=""),
            sa.Column("contact_phone", sa.String(64), nullable=False, server_default=""),
            sa.Column("country", sa.String(64), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("disqualification_reason", sa.Text(), nullable=True),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        )

    inspector = sa.inspect(bind)
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_bidder_package_id",
        "oe_bid_management_bidder",
        ["package_id"],
    )
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_bidder_status",
        "oe_bid_management_bidder",
        ["status"],
    )

    # ── oe_bid_management_submission ────────────────────────────────
    if not _has_table(inspector, "oe_bid_management_submission"):
        op.create_table(
            "oe_bid_management_submission",
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
                "invitation_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_invitation.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "bidder_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_bidder.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("submitted_at", sa.String(40), nullable=True),
            sa.Column("total_amount", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column(
                "completeness_score",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("notes_to_owner", sa.Text(), nullable=False, server_default=""),
            sa.Column("exclusions", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("qualifications", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column(
                "is_valid",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0") if is_sqlite else sa.text("false"),
            ),
            sa.Column(
                "open_after_deadline",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0") if is_sqlite else sa.text("false"),
            ),
            sa.Column("envelope_payload", sa.JSON(), nullable=False, server_default="{}"),
            sa.UniqueConstraint("invitation_id", name="uq_oe_bid_management_submission_invitation_id"),
        )

    inspector = sa.inspect(bind)
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_submission_invitation_id",
        "oe_bid_management_submission",
        ["invitation_id"],
    )
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_submission_bidder_id",
        "oe_bid_management_submission",
        ["bidder_id"],
    )

    # ── oe_bid_management_submission_line ───────────────────────────
    if not _has_table(inspector, "oe_bid_management_submission_line"):
        op.create_table(
            "oe_bid_management_submission_line",
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
                "submission_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_submission.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "line_item_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_line_item.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("unit_price", sa.Numeric(18, 4), nullable=False, server_default="0"),
            sa.Column(
                "quantity_priced",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column("total_price", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column(
                "alternative_offered",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0") if is_sqlite else sa.text("false"),
            ),
            sa.Column(
                "alternative_description",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column("comment", sa.Text(), nullable=False, server_default=""),
        )

    inspector = sa.inspect(bind)
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_submission_line_submission_id",
        "oe_bid_management_submission_line",
        ["submission_id"],
    )
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_submission_line_line_item_id",
        "oe_bid_management_submission_line",
        ["line_item_id"],
    )

    # ── oe_bid_management_qa ────────────────────────────────────────
    if not _has_table(inspector, "oe_bid_management_qa"):
        op.create_table(
            "oe_bid_management_qa",
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
                "package_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "bidder_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_bidder.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("question", sa.Text(), nullable=False, server_default=""),
            sa.Column("asked_at", sa.String(40), nullable=True),
            sa.Column("asked_by_email", sa.String(255), nullable=False, server_default=""),
            sa.Column("answer", sa.Text(), nullable=False, server_default=""),
            sa.Column("answered_at", sa.String(40), nullable=True),
            sa.Column("answered_by", sa.String(36), nullable=True),
            sa.Column(
                "is_public",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("0") if is_sqlite else sa.text("false"),
            ),
            sa.Column(
                "visible_to_bidder_ids",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )

    inspector = sa.inspect(bind)
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_qa_package_id",
        "oe_bid_management_qa",
        ["package_id"],
    )
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_qa_bidder_id",
        "oe_bid_management_qa",
        ["bidder_id"],
    )

    # ── oe_bid_management_comparison ────────────────────────────────
    if not _has_table(inspector, "oe_bid_management_comparison"):
        op.create_table(
            "oe_bid_management_comparison",
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
                "package_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("computed_at", sa.String(40), nullable=True),
            sa.Column(
                "normalized_low",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "normalized_high",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "technical_scoring_rule",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "commercial_weight_pct",
                sa.Integer(),
                nullable=False,
                server_default="100",
            ),
            sa.Column(
                "technical_weight_pct",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "recommended_bidder_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_bidder.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("recommended_reason", sa.Text(), nullable=False, server_default=""),
            sa.UniqueConstraint("package_id", name="uq_oe_bid_management_comparison_package_id"),
        )

    inspector = sa.inspect(bind)
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_comparison_package_id",
        "oe_bid_management_comparison",
        ["package_id"],
    )

    # ── oe_bid_management_leveling ──────────────────────────────────
    if not _has_table(inspector, "oe_bid_management_leveling"):
        op.create_table(
            "oe_bid_management_leveling",
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
                "comparison_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_comparison.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "bidder_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_bidder.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("raw_total", sa.Numeric(18, 2), nullable=False, server_default="0"),
            sa.Column(
                "normalized_total",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "commercial_score",
                sa.Numeric(8, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "technical_score",
                sa.Numeric(8, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column("total_score", sa.Numeric(8, 4), nullable=False, server_default="0"),
            sa.Column("rank", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "manual_adjustment",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "manual_adjustment_reason",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
        )

    inspector = sa.inspect(bind)
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_leveling_comparison_id",
        "oe_bid_management_leveling",
        ["comparison_id"],
    )
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_leveling_bidder_id",
        "oe_bid_management_leveling",
        ["bidder_id"],
    )

    # ── oe_bid_management_award ─────────────────────────────────────
    if not _has_table(inspector, "oe_bid_management_award"):
        op.create_table(
            "oe_bid_management_award",
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
                "package_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "awarded_bidder_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_bidder.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "awarded_amount",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(10), nullable=False, server_default=""),
            sa.Column("decision_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("decision_signed_by", sa.String(36), nullable=True),
            sa.Column("decision_signed_at", sa.String(40), nullable=True),
            sa.Column(
                "contract_template_ref",
                sa.String(255),
                nullable=False,
                server_default="",
            ),
            sa.Column("notified_others_at", sa.String(40), nullable=True),
            sa.UniqueConstraint("package_id", name="uq_oe_bid_management_award_package_id"),
        )

    inspector = sa.inspect(bind)
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_award_package_id",
        "oe_bid_management_award",
        ["package_id"],
    )
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_award_awarded_bidder_id",
        "oe_bid_management_award",
        ["awarded_bidder_id"],
    )

    # ── oe_bid_management_rejection ─────────────────────────────────
    if not _has_table(inspector, "oe_bid_management_rejection"):
        op.create_table(
            "oe_bid_management_rejection",
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
                "package_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "bidder_id",
                guid_type,
                sa.ForeignKey("oe_bid_management_bidder.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "rejection_code",
                sa.String(32),
                nullable=False,
                server_default="other",
            ),
            sa.Column("rejection_reason", sa.Text(), nullable=False, server_default=""),
            sa.Column("notified_at", sa.String(40), nullable=True),
        )

    inspector = sa.inspect(bind)
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_rejection_package_id",
        "oe_bid_management_rejection",
        ["package_id"],
    )
    _safe_create_index(
        inspector,
        "ix_oe_bid_management_rejection_bidder_id",
        "oe_bid_management_rejection",
        ["bidder_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop in reverse FK order
    drop_order = (
        "oe_bid_management_rejection",
        "oe_bid_management_award",
        "oe_bid_management_leveling",
        "oe_bid_management_comparison",
        "oe_bid_management_qa",
        "oe_bid_management_submission_line",
        "oe_bid_management_submission",
        "oe_bid_management_bidder",
        "oe_bid_management_invitation",
        "oe_bid_management_line_item",
        "oe_bid_management_package",
    )
    for table in drop_order:
        if _has_table(inspector, table):
            try:
                op.drop_table(table)
            except sa.exc.OperationalError:
                pass
        inspector = sa.inspect(bind)
