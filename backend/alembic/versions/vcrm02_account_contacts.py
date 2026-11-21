# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""crm - link table between accounts and contacts.

Adds ``oe_crm_account_contact`` so an account lists its contacts and a contact
can be linked from the existing contacts module. Purely additive and guarded,
so a re-run changes nothing; a running install also gets the table from
``create_all``.

Revision ID: vcrm02_account_contacts
Revises: vsrv03_survey_plan_editor
Create Date: 2026-11-20
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "vcrm02_account_contacts"
down_revision: Union[str, Sequence[str], None] = "vsrv03_survey_plan_editor"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_crm_account_contact"

# boot-repair: none - additive table, created by create_all on a running install


def upgrade() -> None:
    """Create the account-contact link table."""
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        _TABLE,
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("account_id", sa.String(36), sa.ForeignKey("oe_crm_account.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(64), nullable=False, server_default=""),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("account_id", "contact_id", name="uq_crm_account_contact"),
    )
    op.create_index(op.f("ix_oe_crm_account_contact_account_id"), _TABLE, ["account_id"])
    op.create_index(op.f("ix_oe_crm_account_contact_contact_id"), _TABLE, ["contact_id"])


def downgrade() -> None:
    """Drop the link table."""
    if _TABLE in sa.inspect(op.get_bind()).get_table_names():
        op.drop_table(_TABLE)
