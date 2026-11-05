# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Customer offers: three tables and the contact billing address.

Fresh databases get the tables from the models; this revision must still be executed
(``alembic upgrade head``, not only stamped) on an existing install, because the new
``billing_address`` column on contacts is not created by ``create_all`` on a table that
already exists. Every step is inspector-guarded, so running it twice is a no-op.

Revision ID: voff01_customer_offers
Revises: vncr01_ncr_due_verified
Create Date: 2026-11-05
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "voff01_customer_offers"
down_revision = "vncr01_ncr_due_verified"
branch_labels = None
depends_on = None

_TABLES = ("oe_offers_offer", "oe_offers_text_block", "oe_offers_settings")


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if all(insp.has_table(t) for t in _TABLES):
        _contact_column(insp)
        return
    from app.database import Base
    from app.modules.offers import models  # noqa: F401 - registers the tables on Base.metadata

    for name in _TABLES:
        if not insp.has_table(name):
            Base.metadata.tables[name].create(bind)
    _contact_column(sa.inspect(bind))


def _contact_column(insp: sa.Inspector) -> None:
    if insp.has_table("oe_contacts_contact") and "billing_address" not in {
        c["name"] for c in insp.get_columns("oe_contacts_contact")
    }:
        op.add_column("oe_contacts_contact", sa.Column("billing_address", sa.JSON(), nullable=True))


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if insp.has_table("oe_contacts_contact") and "billing_address" in {
        c["name"] for c in insp.get_columns("oe_contacts_contact")
    }:
        op.drop_column("oe_contacts_contact", "billing_address")
    for name in reversed(_TABLES):
        if insp.has_table(name):
            op.drop_table(name)
