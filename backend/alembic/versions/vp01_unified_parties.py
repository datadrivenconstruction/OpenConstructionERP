# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""unified parties - one contact identity across tenders and the portal.

Adds a nullable ``contact_id`` (FK ``oe_contacts_contact``, ON DELETE SET NULL) with
``contact_match_method`` and ``contact_match_confidence`` to ``oe_tendering_bid``,
``oe_tendering_bid_invitation`` and ``oe_portal_user``, and creates
``oe_contacts_party_review`` (candidate links a person confirms or rejects).
Existing rows keep ``contact_id`` NULL: the link is made by the admin backfill
endpoint, never by the migration. Nothing is deleted. Inspector-guarded, so a
database whose tables ``create_all`` already built is a no-op.

Revision ID: vp01_unified_parties
Revises: v3331_cost_benchmarks_payroll_periods
Create Date: 2026-10-29
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vp01_unified_parties"
down_revision: str | Sequence[str] | None = "v3331_cost_benchmarks_payroll_periods"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LINKED = ("oe_tendering_bid", "oe_tendering_bid_invitation", "oe_portal_user")
_REVIEW = "oe_contacts_party_review"


def _guid() -> sa.types.TypeEngine:
    from app.database import GUID

    return GUID()


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    for table in _LINKED:
        if table not in tables:
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        with op.batch_alter_table(table) as batch:
            if "contact_id" not in cols:
                batch.add_column(sa.Column("contact_id", _guid(), nullable=True))
                batch.create_foreign_key(
                    f"fk_{table}_contact_id_oe_contacts_contact",
                    "oe_contacts_contact",
                    ["contact_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
                batch.create_index(f"ix_{table}_contact_id", ["contact_id"])
            if "contact_match_method" not in cols:
                batch.add_column(sa.Column("contact_match_method", sa.String(20), nullable=True))
            if "contact_match_confidence" not in cols:
                batch.add_column(sa.Column("contact_match_confidence", sa.Float(), nullable=True))
    if _REVIEW not in tables:
        op.create_table(
            _REVIEW,
            sa.Column("id", _guid(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("entity_type", sa.String(30), nullable=False),
            sa.Column("entity_id", _guid(), nullable=False),
            sa.Column(
                "contact_id",
                _guid(),
                sa.ForeignKey("oe_contacts_contact.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("method", sa.String(20), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("reason", sa.String(20), nullable=False, server_default="weak"),
            sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
            sa.Column("owner_id", sa.String(36), nullable=True),
            sa.Column("reviewed_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("entity_type", "entity_id", "contact_id", name="uq_oe_contacts_party_review"),
        )
        for col in ("entity_type", "entity_id", "contact_id", "status", "owner_id"):
            op.create_index(f"ix_{_REVIEW}_{col}", _REVIEW, [col])


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    tables = set(insp.get_table_names())
    if _REVIEW in tables:
        op.drop_table(_REVIEW)
    for table in _LINKED:
        if table not in tables:
            continue
        cols = {c["name"] for c in insp.get_columns(table)}
        with op.batch_alter_table(table) as batch:
            if "contact_id" in cols:
                batch.drop_index(f"ix_{table}_contact_id")
                batch.drop_constraint(f"fk_{table}_contact_id_oe_contacts_contact", type_="foreignkey")
                batch.drop_column("contact_id")
            for name in ("contact_match_method", "contact_match_confidence"):
                if name in cols:
                    batch.drop_column(name)
