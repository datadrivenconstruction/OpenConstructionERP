# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""cvr + cost_recovery - link payment applications to claims, back-charges to parties and sources.

A CVR interim payment application stood alone: nothing said which contract
progress claim it was raised from. A back-charge named the party it is charged
to and the record it came from only as free text, so no query could answer
"what does this subcontractor still owe us back".

Five nullable columns, all additive:

``oe_cvr_payment_application.progress_claim_id``
    The contract progress claim the application was raised from.
``oe_cost_recovery_back_charge.subcontractor_id`` and ``contact_id``
    The responsible party as a record; ``responsible_party`` stays as the
    free-text fallback.
``oe_cost_recovery_back_charge.ncr_id`` and ``punch_item_id``
    The NCR or punch item the cost arose from.

Each gets the index its model declares with ``index=True``, created here under
exactly the auto-generated name so a database that ``create_all`` already
built does not get a second one.

The columns are plain ``VARCHAR(36)`` with no foreign key, matching ``GUID``
and the cross-module convention (see ``v43_sub_rollup_links``): the claims,
subcontractors, contacts, NCR and punch item tables belong to other modules.
The services check every id before storing it.

This one does NOT need running by hand. It is DDL only and nothing is
backfilled: every existing row is correctly "not linked". The boot schema heal
adds missing nullable columns and plain indexes from the models, so a running
install that boots the new code gets them without an upgrade; the revision
exists so that ``alembic upgrade head`` builds the same schema. Inspector-
guarded, so an install whose schema came from ``create_all`` plus the heal
reaches this revision and adds nothing.

Revision ID: v47_cvr_claim_backcharge_links
Revises: v46_erp_chat_action
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v47_cvr_claim_backcharge_links"
down_revision: Union[str, Sequence[str], None] = "v46_erp_chat_action"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, index name). The index names are the ones ``index=True``
# produces on the models, read off ``__table__.indexes``.
_COLUMNS: tuple[tuple[str, str, str], ...] = (
    (
        "oe_cvr_payment_application",
        "progress_claim_id",
        "ix_oe_cvr_payment_application_progress_claim_id",
    ),
    (
        "oe_cost_recovery_back_charge",
        "subcontractor_id",
        "ix_oe_cost_recovery_back_charge_subcontractor_id",
    ),
    (
        "oe_cost_recovery_back_charge",
        "contact_id",
        "ix_oe_cost_recovery_back_charge_contact_id",
    ),
    (
        "oe_cost_recovery_back_charge",
        "ncr_id",
        "ix_oe_cost_recovery_back_charge_ncr_id",
    ),
    (
        "oe_cost_recovery_back_charge",
        "punch_item_id",
        "ix_oe_cost_recovery_back_charge_punch_item_id",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, column, index_name in _COLUMNS:
        if table not in tables:
            # The revision that creates the table has not run on this
            # database, so there is nothing to extend.
            continue
        existing_columns = {c["name"] for c in inspector.get_columns(table)}
        if column not in existing_columns:
            op.add_column(table, sa.Column(column, sa.String(length=36), nullable=True))
        existing_indexes = {ix["name"] for ix in inspector.get_indexes(table)}
        if index_name not in existing_indexes:
            op.create_index(index_name, table, [column])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    for table, column, index_name in reversed(_COLUMNS):
        if table not in tables:
            continue
        if index_name in {ix["name"] for ix in inspector.get_indexes(table)}:
            op.drop_index(index_name, table_name=table)
        if column in {c["name"] for c in inspector.get_columns(table)}:
            op.drop_column(table, column)
