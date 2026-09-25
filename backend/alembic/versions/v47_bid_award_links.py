# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""bid_management - link bidders to the directory and scope lines to the bill.

An award turns the winning bidder into the counterparty of a contract draft,
and the scope lines of the package into its schedule of values. Until now a
bidder was only a free-text company, so the contract pointed at the bidder
row, which no contracts or finance reader can resolve, and a scope line had no
way to say which bill position it was lifted from.

Three nullable columns, all additive:

``oe_bid_management_bidder.subcontractor_id``
    The subcontractor directory entry the bidder was invited from.
``oe_bid_management_bidder.contact_id``
    The contact that stands for the bidder, set by hand or derived from the
    subcontractor's own contact.
``oe_bid_management_line_item.boq_position_id``
    The bill position a scope line was added from.

Each gets the index its model declares with ``index=True``, created here under
exactly the auto-generated name so a database that ``create_all`` already
built does not get a second one.

The columns are plain ``VARCHAR(36)`` with no foreign key, matching ``GUID``
and the module's cross-module convention: the subcontractor, contact and BOQ
tables are owned by other modules.

DDL only, nothing is backfilled: an existing bidder is correctly "not linked",
and the award falls back to its free-text company name. Inspector-guarded, so
an install whose schema came from ``create_all`` plus the boot heal reaches
this revision and adds nothing.

Revision ID: v47_bid_award_links
Revises: v46_erp_chat_action
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v47_bid_award_links"
down_revision: Union[str, Sequence[str], None] = "v46_erp_chat_action"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# (table, column, index name). The index names are the ones ``index=True``
# produces on the models, read off ``__table__.indexes``.
_COLUMNS: tuple[tuple[str, str, str], ...] = (
    (
        "oe_bid_management_bidder",
        "subcontractor_id",
        "ix_oe_bid_management_bidder_subcontractor_id",
    ),
    (
        "oe_bid_management_bidder",
        "contact_id",
        "ix_oe_bid_management_bidder_contact_id",
    ),
    (
        "oe_bid_management_line_item",
        "boq_position_id",
        "ix_oe_bid_management_line_item_boq_position_id",
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
