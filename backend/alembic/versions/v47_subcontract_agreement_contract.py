# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""subcontractors - link a subcontract agreement to the same subcontract in contracts.

One subcontract could be written twice, as an agreement on the Subcontractors
page and as a contract with ``counterparty_type="subcontractor"``, and nothing
said the two were the same spend, so signing both committed the budget twice.
``oe_subcontractors_agreement.contract_id`` names the contract an agreement
stands for; when it is set the agreement carries the commitment and the
contract does not.

One nullable column with the index its model declares (``index=True``), under
exactly the auto-generated name, so a database that ``create_all`` already
built does not get a second one. Plain ``VARCHAR(36)`` with no foreign key,
matching ``GUID`` and the cross-module convention used by ``prime_contract_id``
(``v43_sub_rollup_links``): the contracts tables belong to another module.

DDL only, nothing is backfilled: every existing agreement is correctly "not
linked". Inspector-guarded, so an install whose schema came from
``create_all`` plus the boot heal reaches this revision and adds nothing.

Revision ID: v47_subcontract_agreement_contract
Revises: v47_cvr_claim_backcharge_links
Create Date: 2026-09-25
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v47_subcontract_agreement_contract"
down_revision: Union[str, Sequence[str], None] = "v47_cvr_claim_backcharge_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_subcontractors_agreement"
_COLUMN = "contract_id"
_INDEX = "ix_oe_subcontractors_agreement_contract_id"


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
