# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3103 — property_dev R6: Lead / Reservation / SPA / PaymentSchedule.

R6 extends ``property_dev`` with a full sales-pipeline backbone:

  - ``oe_property_dev_lead``                  (top-of-funnel leads)
  - ``oe_property_dev_reservation``           (standalone reservations)
  - ``oe_property_dev_sales_contract``        (SPA)
  - ``oe_property_dev_sales_contract_revision`` (terms snapshots)
  - ``oe_property_dev_payment_schedule``      (parent schedule, 1:1 SPA)
  - ``oe_property_dev_instalment``            (child lines)
  - ``oe_property_dev_contract_party``        (multi-buyer junction)

Also drops ``uq_oe_property_dev_buyer_plot`` so a plot can be linked to
multiple buyers through :class:`ContractParty`. Existing Buyer rows are
left untouched — :class:`ContractParty` creation is opt-in via the new
API.

Idempotent: each operation guards on inspector-reflected state so the
migration is a no-op when ``Base.metadata.create_all`` has already
materialised the tables (the dev-bootstrap path) — matches the v3018
foundation migration.

Revision ID: v3103_propdev_lead_reservation_spa_schedule_parties
Revises: v3102_round5_merge
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3103_propdev_lead_reservation_spa_schedule_parties"
down_revision: Union[str, Sequence[str], None] = "v3102_round5_merge"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_table(inspector: sa.engine.reflection.Inspector, table: str) -> bool:
    return table in inspector.get_table_names()


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def _has_unique(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return name in {u["name"] for u in inspector.get_unique_constraints(table)}


def upgrade() -> None:  # noqa: PLR0915 — single linear bootstrap
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── Drop Buyer plot_id uniqueness (multi-buyer SPAs) ────────────
    # SQLite has no ALTER TABLE DROP CONSTRAINT — must go through batch
    # mode (copy-and-move). On PostgreSQL batch_alter_table still works
    # via a no-op recreate so this stays portable.
    if _has_unique(inspector, "oe_property_dev_buyer", "uq_oe_property_dev_buyer_plot"):
        with op.batch_alter_table("oe_property_dev_buyer") as batch_op:
            batch_op.drop_constraint(
                "uq_oe_property_dev_buyer_plot",
                type_="unique",
            )

    # ── Lead ─────────────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_lead"):
        op.create_table(
            "oe_property_dev_lead",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "development_id",
                sa.String(length=36),
                sa.ForeignKey("oe_property_dev_development.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column(
                "source",
                sa.String(length=40),
                nullable=False,
                server_default="other",
            ),
            sa.Column(
                "lead_score",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "assigned_agent_user_id",
                sa.String(length=36),
                nullable=True,
            ),
            sa.Column(
                "status",
                sa.String(length=40),
                nullable=False,
                server_default="new",
            ),
            sa.Column("nurture_stage", sa.Text(), nullable=True),
            sa.Column("full_name", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("email", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("phone", sa.String(length=40), nullable=True),
            sa.Column("language", sa.String(length=10), nullable=False, server_default="en"),
            sa.Column("budget_min", sa.Numeric(15, 2), nullable=True),
            sa.Column("budget_max", sa.Numeric(15, 2), nullable=True),
            sa.Column("currency", sa.String(length=8), nullable=False, server_default=""),
            sa.Column(
                "preferred_house_type_id",
                sa.String(length=36),
                sa.ForeignKey("oe_property_dev_house_type.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column(
                "converted_to_buyer_id",
                sa.String(length=36),
                sa.ForeignKey("oe_property_dev_buyer.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "metadata",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
        )

    inspector = sa.inspect(bind)
    for name, cols in (
        ("ix_oe_property_dev_lead_development_id", ("development_id",)),
        ("ix_oe_property_dev_lead_tenant_id", ("tenant_id",)),
        ("ix_oe_property_dev_lead_source", ("source",)),
        ("ix_oe_property_dev_lead_status", ("status",)),
        ("ix_oe_property_dev_lead_assigned_agent_user_id", ("assigned_agent_user_id",)),
        ("ix_oe_property_dev_lead_email", ("email",)),
    ):
        if not _has_index(inspector, "oe_property_dev_lead", name):
            op.create_index(name, "oe_property_dev_lead", list(cols))

    # ── Reservation ──────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_reservation"):
        op.create_table(
            "oe_property_dev_reservation",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "plot_id",
                sa.String(length=36),
                sa.ForeignKey("oe_property_dev_plot.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "lead_id",
                sa.String(length=36),
                sa.ForeignKey("oe_property_dev_lead.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "buyer_id",
                sa.String(length=36),
                sa.ForeignKey("oe_property_dev_buyer.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column("reservation_number", sa.String(length=80), nullable=False),
            sa.Column(
                "deposit_amount",
                sa.Numeric(15, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default=""),
            sa.Column("deposit_paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "cooling_off_days",
                sa.Integer(),
                nullable=False,
                server_default="7",
            ),
            sa.Column("cooling_off_until", sa.String(length=20), nullable=True),
            sa.Column("expires_at", sa.String(length=20), nullable=True),
            sa.Column(
                "status",
                sa.String(length=40),
                nullable=False,
                server_default="active",
            ),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "plot_id",
                "reservation_number",
                name="uq_oe_property_dev_reservation_plot_number",
            ),
        )

    inspector = sa.inspect(bind)
    for name, cols in (
        ("ix_oe_property_dev_reservation_plot_id", ("plot_id",)),
        ("ix_oe_property_dev_reservation_tenant_id", ("tenant_id",)),
        ("ix_oe_property_dev_reservation_status", ("status",)),
    ):
        if not _has_index(inspector, "oe_property_dev_reservation", name):
            op.create_index(name, "oe_property_dev_reservation", list(cols))

    # ── SalesContract ────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_sales_contract"):
        op.create_table(
            "oe_property_dev_sales_contract",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("contract_number", sa.String(length=80), nullable=False),
            sa.Column(
                "plot_id",
                sa.String(length=36),
                sa.ForeignKey("oe_property_dev_plot.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "reservation_id",
                sa.String(length=36),
                sa.ForeignKey("oe_property_dev_reservation.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column("signing_date", sa.String(length=20), nullable=True),
            sa.Column(
                "governing_law",
                sa.String(length=16),
                nullable=False,
                server_default="",
            ),
            sa.Column("language", sa.String(length=10), nullable=False, server_default="en"),
            sa.Column(
                "total_price_breakdown",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column(
                "total_value",
                sa.Numeric(15, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default=""),
            sa.Column("e_sign_envelope_id", sa.String(length=255), nullable=True),
            sa.Column(
                "status",
                sa.String(length=40),
                nullable=False,
                server_default="draft",
            ),
            sa.Column(
                "parent_contract_id",
                sa.String(length=36),
                sa.ForeignKey("oe_property_dev_sales_contract.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "revision_number",
                sa.Integer(),
                nullable=False,
                server_default="1",
            ),
            sa.Column(
                "terms_version",
                sa.String(length=80),
                nullable=False,
                server_default="",
            ),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "plot_id",
                "contract_number",
                name="uq_oe_property_dev_sales_contract_plot_number",
            ),
        )

    inspector = sa.inspect(bind)
    for name, cols in (
        ("ix_oe_property_dev_sales_contract_plot_id", ("plot_id",)),
        ("ix_oe_property_dev_sales_contract_tenant_id", ("tenant_id",)),
        ("ix_oe_property_dev_sales_contract_status", ("status",)),
    ):
        if not _has_index(inspector, "oe_property_dev_sales_contract", name):
            op.create_index(name, "oe_property_dev_sales_contract", list(cols))

    # ── SalesContractRevision ────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_sales_contract_revision"):
        op.create_table(
            "oe_property_dev_sales_contract_revision",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "contract_id",
                sa.String(length=36),
                sa.ForeignKey("oe_property_dev_sales_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("revision_number", sa.Integer(), nullable=False),
            sa.Column(
                "terms_blob",
                sa.JSON(),
                nullable=False,
                server_default="{}",
            ),
            sa.Column("created_by_user_id", sa.String(length=36), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "contract_id",
                "revision_number",
                name="uq_oe_property_dev_sales_contract_revision_rev",
            ),
        )

    inspector = sa.inspect(bind)
    if not _has_index(
        inspector,
        "oe_property_dev_sales_contract_revision",
        "ix_oe_property_dev_sales_contract_revision_contract_id",
    ):
        op.create_index(
            "ix_oe_property_dev_sales_contract_revision_contract_id",
            "oe_property_dev_sales_contract_revision",
            ["contract_id"],
        )

    # ── PaymentSchedule ─────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_payment_schedule"):
        op.create_table(
            "oe_property_dev_payment_schedule",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "sales_contract_id",
                sa.String(length=36),
                sa.ForeignKey("oe_property_dev_sales_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("tenant_id", sa.String(length=36), nullable=True),
            sa.Column("currency", sa.String(length=3), nullable=False, server_default=""),
            sa.Column(
                "total_amount",
                sa.Numeric(15, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "late_fee_pct",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "grace_period_days",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "status",
                sa.String(length=40),
                nullable=False,
                server_default="active",
            ),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "sales_contract_id",
                name="uq_oe_property_dev_payment_schedule_contract",
            ),
        )

    inspector = sa.inspect(bind)
    for name, cols in (
        ("ix_oe_property_dev_payment_schedule_contract_id", ("sales_contract_id",)),
        ("ix_oe_property_dev_payment_schedule_tenant_id", ("tenant_id",)),
        ("ix_oe_property_dev_payment_schedule_status", ("status",)),
    ):
        if not _has_index(inspector, "oe_property_dev_payment_schedule", name):
            op.create_index(name, "oe_property_dev_payment_schedule", list(cols))

    # ── Instalment ──────────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_instalment"):
        op.create_table(
            "oe_property_dev_instalment",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "schedule_id",
                sa.String(length=36),
                sa.ForeignKey(
                    "oe_property_dev_payment_schedule.id",
                    ondelete="CASCADE",
                ),
                nullable=False,
            ),
            sa.Column("sequence", sa.Integer(), nullable=False),
            sa.Column(
                "milestone_label",
                sa.String(length=255),
                nullable=False,
                server_default="",
            ),
            sa.Column(
                "milestone_event",
                sa.String(length=80),
                nullable=False,
                server_default="",
            ),
            sa.Column("due_date", sa.String(length=20), nullable=True),
            sa.Column(
                "amount",
                sa.Numeric(15, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "amount_paid",
                sa.Numeric(15, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("paid_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "status",
                sa.String(length=40),
                nullable=False,
                server_default="pending",
            ),
            sa.Column(
                "late_fee_accrued",
                sa.Numeric(15, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column("invoice_ref", sa.String(length=255), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "schedule_id",
                "sequence",
                name="uq_oe_property_dev_instalment_schedule_seq",
            ),
        )

    inspector = sa.inspect(bind)
    for name, cols in (
        ("ix_oe_property_dev_instalment_schedule_id", ("schedule_id",)),
        ("ix_oe_property_dev_instalment_milestone_event", ("milestone_event",)),
        ("ix_oe_property_dev_instalment_status", ("status",)),
    ):
        if not _has_index(inspector, "oe_property_dev_instalment", name):
            op.create_index(name, "oe_property_dev_instalment", list(cols))

    # ── ContractParty ───────────────────────────────────────────────
    if not _has_table(inspector, "oe_property_dev_contract_party"):
        op.create_table(
            "oe_property_dev_contract_party",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "sales_contract_id",
                sa.String(length=36),
                sa.ForeignKey("oe_property_dev_sales_contract.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "buyer_id",
                sa.String(length=36),
                sa.ForeignKey("oe_property_dev_buyer.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "ownership_pct",
                sa.Numeric(5, 2),
                nullable=False,
                server_default="0",
            ),
            sa.Column(
                "party_role",
                sa.String(length=40),
                nullable=False,
                server_default="primary",
            ),
            sa.Column(
                "signing_order",
                sa.Integer(),
                nullable=False,
                server_default="0",
            ),
            sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("signature_ref", sa.String(length=255), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.func.now(),
            ),
            sa.UniqueConstraint(
                "sales_contract_id",
                "buyer_id",
                name="uq_oe_property_dev_contract_party_contract_buyer",
            ),
        )

    inspector = sa.inspect(bind)
    for name, cols in (
        ("ix_oe_property_dev_contract_party_sales_contract_id", ("sales_contract_id",)),
        ("ix_oe_property_dev_contract_party_buyer_id", ("buyer_id",)),
    ):
        if not _has_index(inspector, "oe_property_dev_contract_party", name):
            op.create_index(name, "oe_property_dev_contract_party", list(cols))


def downgrade() -> None:
    """Drop the R6 tables in FK-safe order.

    Re-add the dropped Buyer.plot_id uniqueness only if no buyer
    currently shares a plot — otherwise leave the constraint absent and
    let the operator resolve duplicates first.
    """
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for tbl in (
        "oe_property_dev_contract_party",
        "oe_property_dev_instalment",
        "oe_property_dev_payment_schedule",
        "oe_property_dev_sales_contract_revision",
        "oe_property_dev_sales_contract",
        "oe_property_dev_reservation",
        "oe_property_dev_lead",
    ):
        if _has_table(inspector, tbl):
            op.drop_table(tbl)

    inspector = sa.inspect(bind)
    if _has_table(inspector, "oe_property_dev_buyer") and not _has_unique(
        inspector, "oe_property_dev_buyer", "uq_oe_property_dev_buyer_plot"
    ):
        # Best-effort restore — skip silently if duplicate plot_ids exist.
        try:
            op.create_unique_constraint(
                "uq_oe_property_dev_buyer_plot",
                "oe_property_dev_buyer",
                ["plot_id"],
            )
        except sa.exc.IntegrityError:
            pass
