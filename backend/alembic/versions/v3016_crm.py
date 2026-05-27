# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""crm — sales pipeline schema (accounts/leads/opportunities/activities).

Creates 9 tables for Module 18 (CRM Sales Pipeline):

    oe_crm_pipeline_stage
    oe_crm_win_loss_reason
    oe_crm_pipeline_stage_config        (singleton-ish config)
    oe_crm_account
    oe_crm_lead
    oe_crm_opportunity
    oe_crm_opportunity_stage_history
    oe_crm_activity
    oe_crm_forecast

Idempotent — re-applying on a DB where ``Base.metadata.create_all`` has
already created these tables is a no-op. ``op.create_index`` calls are
wrapped in ``try/except OperationalError`` for tolerance on partial state.

NOTE: ``primary_contact_id`` (in oe_crm_account and oe_crm_opportunity)
is a plain UUID column with NO foreign key to ``oe_contacts_contact`` —
the ORM does not declare an FK here, and the migration follows suit so
test fixtures that load only projects/users still work.

Revision ID: v3016_crm
Revises: v3013_portal
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3016_crm"
down_revision: Union[str, Sequence[str], None] = "v3015_contracts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table_name, list of (index_name, column tuple, unique))
_INDEXES: list[tuple[str, list[tuple[str, tuple[str, ...], bool]]]] = [
    (
        "oe_crm_pipeline_stage",
        [
            ("ix_oe_crm_pipeline_stage_code", ("code",), True),
        ],
    ),
    (
        "oe_crm_win_loss_reason",
        [
            ("ix_oe_crm_win_loss_reason_code", ("code",), True),
        ],
    ),
    (
        "oe_crm_account",
        [
            ("ix_oe_crm_account_name", ("name",), False),
            ("ix_oe_crm_account_status", ("status",), False),
            ("ix_oe_crm_account_owner_user_id", ("owner_user_id",), False),
        ],
    ),
    (
        "oe_crm_lead",
        [
            ("ix_oe_crm_lead_account_id", ("account_id",), False),
            ("ix_oe_crm_lead_status", ("status",), False),
            ("ix_oe_crm_lead_assigned_to", ("assigned_to",), False),
        ],
    ),
    (
        "oe_crm_opportunity",
        [
            ("ix_oe_crm_opportunity_account_id", ("account_id",), False),
            ("ix_oe_crm_opportunity_stage_id", ("stage_id",), False),
            ("ix_oe_crm_opportunity_owner_user_id", ("owner_user_id",), False),
            ("ix_oe_crm_opportunity_status", ("status",), False),
        ],
    ),
    (
        "oe_crm_opportunity_stage_history",
        [
            (
                "ix_oe_crm_opportunity_stage_history_opportunity_id",
                ("opportunity_id",),
                False,
            ),
        ],
    ),
    (
        "oe_crm_activity",
        [
            ("ix_oe_crm_activity_owner_user_id", ("owner_user_id",), False),
            ("ix_oe_crm_activity_account_id", ("account_id",), False),
            ("ix_oe_crm_activity_opportunity_id", ("opportunity_id",), False),
            ("ix_oe_crm_activity_lead_id", ("lead_id",), False),
            ("ix_oe_crm_activity_due_at", ("due_at",), False),
        ],
    ),
    (
        "oe_crm_forecast",
        [
            ("ix_oe_crm_forecast_period", ("period",), False),
        ],
    ),
]


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == name for ix in inspector.get_indexes(table))


def _ts_cols() -> list[sa.Column]:
    """created_at + updated_at columns matching app.database.Base."""
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

    # ── oe_crm_pipeline_stage ────────────────────────────────────────────
    if not _has_table(inspector, "oe_crm_pipeline_stage"):
        op.create_table(
            "oe_crm_pipeline_stage",
            sa.Column("id", guid, primary_key=True),
            *_ts_cols(),
            sa.Column("code", sa.String(64), nullable=False, unique=True),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("display_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "default_probability_percent",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("is_final", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("is_won", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("is_lost", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("color", sa.String(16), nullable=False, server_default=""),
        )

    # ── oe_crm_win_loss_reason ───────────────────────────────────────────
    if not _has_table(inspector, "oe_crm_win_loss_reason"):
        op.create_table(
            "oe_crm_win_loss_reason",
            sa.Column("id", guid, primary_key=True),
            *_ts_cols(),
            sa.Column("code", sa.String(64), nullable=False, unique=True),
            sa.Column("label", sa.String(255), nullable=False),
            sa.Column(
                "category",
                sa.String(32),
                nullable=False,
                server_default="other",
            ),
            sa.Column(
                "is_win_reason",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "is_loss_reason",
                sa.Boolean(),
                nullable=False,
                server_default="1",
            ),
        )

    # ── oe_crm_pipeline_stage_config ────────────────────────────────────
    if not _has_table(inspector, "oe_crm_pipeline_stage_config"):
        op.create_table(
            "oe_crm_pipeline_stage_config",
            sa.Column("id", sa.String(64), primary_key=True),
            *_ts_cols(),
            sa.Column(
                "kanban_columns",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
            sa.Column(
                "defaults",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
        )

    # ── oe_crm_account ──────────────────────────────────────────────────
    if not _has_table(inspector, "oe_crm_account"):
        op.create_table(
            "oe_crm_account",
            sa.Column("id", guid, primary_key=True),
            *_ts_cols(),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("industry", sa.String(128), nullable=True),
            sa.Column(
                "size_category",
                sa.String(32),
                nullable=False,
                server_default="sme",
            ),
            sa.Column("country", sa.String(64), nullable=True),
            sa.Column("website", sa.String(500), nullable=True),
            # NOTE: plain UUID — NO FK to oe_contacts_contact.
            sa.Column("primary_contact_id", guid, nullable=True),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="active",
            ),
            sa.Column(
                "owner_user_id",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("tags", sa.JSON(), nullable=False, server_default="[]"),
        )

    # ── oe_crm_opportunity (referenced by lead, must come BEFORE lead) ──
    # ... wait: Lead has converted_opportunity_id → Opportunity, but
    # Opportunity has no FK back to Lead, so creating Opportunity first
    # would be ideal — but Opportunity has FK to oe_crm_account already
    # created above. Lead has FK to Account + Opportunity. We create
    # Opportunity before Lead so Lead's FK target exists.

    if not _has_table(inspector, "oe_crm_opportunity"):
        op.create_table(
            "oe_crm_opportunity",
            sa.Column("id", guid, primary_key=True),
            *_ts_cols(),
            sa.Column(
                "account_id",
                guid,
                sa.ForeignKey("oe_crm_account.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "estimated_value",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(8), nullable=False, server_default=""),
            sa.Column("expected_close_date", sa.String(20), nullable=True),
            sa.Column(
                "probability_percent",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "stage_id",
                guid,
                sa.ForeignKey("oe_crm_pipeline_stage.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column(
                "weighted_value",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "source",
                sa.String(32),
                nullable=False,
                server_default="inbound",
            ),
            sa.Column(
                "owner_user_id",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="open",
            ),
            sa.Column("won_at", sa.String(40), nullable=True),
            sa.Column("lost_at", sa.String(40), nullable=True),
            sa.Column(
                "lost_reason_code",
                sa.String(64),
                sa.ForeignKey("oe_crm_win_loss_reason.code", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            # NOTE: plain UUID — NO FK to oe_contacts_contact.
            sa.Column("primary_contact_id", guid, nullable=True),
            sa.Column(
                "competitor_names",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )

    # ── oe_crm_lead ─────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_crm_lead"):
        op.create_table(
            "oe_crm_lead",
            sa.Column("id", guid, primary_key=True),
            *_ts_cols(),
            sa.Column(
                "account_id",
                guid,
                sa.ForeignKey("oe_crm_account.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("contact_name", sa.String(255), nullable=False),
            sa.Column("contact_email", sa.String(255), nullable=True),
            sa.Column("contact_phone", sa.String(64), nullable=True),
            sa.Column(
                "source",
                sa.String(32),
                nullable=False,
                server_default="inbound",
            ),
            sa.Column(
                "status",
                sa.String(32),
                nullable=False,
                server_default="new",
            ),
            sa.Column(
                "assigned_to",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "qualification_notes",
                sa.Text(),
                nullable=False,
                server_default="",
            ),
            sa.Column("qualified_at", sa.String(40), nullable=True),
            sa.Column("converted_at", sa.String(40), nullable=True),
            sa.Column(
                "converted_opportunity_id",
                guid,
                sa.ForeignKey("oe_crm_opportunity.id", ondelete="SET NULL"),
                nullable=True,
            ),
        )

    # ── oe_crm_opportunity_stage_history ────────────────────────────────
    if not _has_table(inspector, "oe_crm_opportunity_stage_history"):
        op.create_table(
            "oe_crm_opportunity_stage_history",
            sa.Column("id", guid, primary_key=True),
            *_ts_cols(),
            sa.Column(
                "opportunity_id",
                guid,
                sa.ForeignKey("oe_crm_opportunity.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "from_stage_id",
                guid,
                sa.ForeignKey("oe_crm_pipeline_stage.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "to_stage_id",
                guid,
                sa.ForeignKey("oe_crm_pipeline_stage.id", ondelete="RESTRICT"),
                nullable=False,
            ),
            sa.Column("changed_at", sa.String(40), nullable=True),
            sa.Column(
                "changed_by",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("duration_in_previous_seconds", sa.Integer(), nullable=True),
        )

    # ── oe_crm_activity ─────────────────────────────────────────────────
    if not _has_table(inspector, "oe_crm_activity"):
        op.create_table(
            "oe_crm_activity",
            sa.Column("id", guid, primary_key=True),
            *_ts_cols(),
            sa.Column(
                "owner_user_id",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "account_id",
                guid,
                sa.ForeignKey("oe_crm_account.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "opportunity_id",
                guid,
                sa.ForeignKey("oe_crm_opportunity.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column(
                "lead_id",
                guid,
                sa.ForeignKey("oe_crm_lead.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("kind", sa.String(32), nullable=False, server_default="note"),
            sa.Column("subject", sa.String(500), nullable=False, server_default=""),
            sa.Column("body", sa.Text(), nullable=False, server_default=""),
            sa.Column("due_at", sa.String(40), nullable=True),
            sa.Column("completed_at", sa.String(40), nullable=True),
            sa.Column("outcome", sa.String(32), nullable=True),
            sa.Column("external_calendar_event_id", sa.String(255), nullable=True),
        )

    # ── oe_crm_forecast ─────────────────────────────────────────────────
    if not _has_table(inspector, "oe_crm_forecast"):
        op.create_table(
            "oe_crm_forecast",
            sa.Column("id", guid, primary_key=True),
            *_ts_cols(),
            sa.Column("period", sa.String(16), nullable=False),
            sa.Column(
                "owner_user_id",
                guid,
                sa.ForeignKey("oe_users_user.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "pipeline_value",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "weighted_value",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "won_value",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "committed_value",
                sa.Numeric(18, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("computed_at", sa.String(40), nullable=True),
        )

    # ── Indexes (idempotent + OperationalError-tolerant) ────────────────
    inspector = sa.inspect(bind)
    for table, indexes in _INDEXES:
        if not _has_table(inspector, table):
            continue
        for name, cols, unique in indexes:
            if _has_index(inspector, table, name):
                continue
            try:
                op.create_index(name, table, list(cols), unique=unique)
            except sa.exc.OperationalError:
                # Index race / duplicate name from a partial migration
                # state — log + ignore. Re-running is safe.
                pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop indexes first
    for table, indexes in _INDEXES:
        if not _has_table(inspector, table):
            continue
        for name, _cols, _unique in indexes:
            if _has_index(inspector, table, name):
                try:
                    op.drop_index(name, table_name=table)
                except sa.exc.OperationalError:
                    pass

    # Drop tables in reverse dependency order
    for tbl in (
        "oe_crm_forecast",
        "oe_crm_activity",
        "oe_crm_opportunity_stage_history",
        "oe_crm_lead",
        "oe_crm_opportunity",
        "oe_crm_account",
        "oe_crm_pipeline_stage_config",
        "oe_crm_win_loss_reason",
        "oe_crm_pipeline_stage",
    ):
        if _has_table(inspector, tbl):
            op.drop_table(tbl)
