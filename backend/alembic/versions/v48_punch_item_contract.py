# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""punchlist - attribute a punch item to a contract.

``oe_punchlist_item.contract_id`` names the contract whose scope an item
belongs to, so a project with several contracts can keep each one's punch list
apart and a retention release withholds only for the items that could be its
own. Null means "not attributed", which every existing item correctly is.

One nullable column with the index its model declares (``index=True``), under
exactly the auto-generated name, so a database that ``create_all`` already
built does not get a second one. Plain ``VARCHAR(36)`` with no foreign key,
the cross-module convention ``v47_subcontract_agreement_contract`` follows: the
contracts tables belong to another module.

DDL only, nothing is backfilled. Inspector-guarded, so an install whose schema
came from ``create_all`` plus the boot heal reaches this revision and adds
nothing.

Revision ID: v48_punch_item_contract
Revises: v48_project_jurisdiction_unit_system
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v48_punch_item_contract"
down_revision: Union[str, Sequence[str], None] = "v48_project_jurisdiction_unit_system"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_punchlist_item"
_COLUMN = "contract_id"
_INDEX = "ix_oe_punchlist_item_contract_id"


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        # The module's tables were never created here, so there is nothing
        # to extend; adding to an absent table would stop the upgrade.
        return
    if _COLUMN not in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.add_column(_TABLE, sa.Column(_COLUMN, sa.String(length=36), nullable=True))
    if _INDEX not in {ix["name"] for ix in inspector.get_indexes(_TABLE)}:
        op.create_index(_INDEX, _TABLE, [_COLUMN])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return
    if _INDEX in {ix["name"] for ix in inspector.get_indexes(_TABLE)}:
        op.drop_index(_INDEX, table_name=_TABLE)
    if _COLUMN in {c["name"] for c in inspector.get_columns(_TABLE)}:
        op.drop_column(_TABLE, _COLUMN)
