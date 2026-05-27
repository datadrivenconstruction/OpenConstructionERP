# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3101_service_number_uniques — race-safe number allocation guard.

Round-5 service-module deep audit found that ``next_contract_number()``,
``next_ticket_number(contract_id)`` and ``next_work_order_number()`` each
read ``COUNT(*)`` then format-string concat the result into a label.
Under concurrent insert load (two dispatchers POSTing /tickets/ to the
same contract, or two recurring-schedule materialisers firing in parallel
on the same cron tick) the two requests race past the same COUNT and
produce identical labels. The service layer now retries on
IntegrityError; that retry is only effective if the DB actually has a
unique index to raise it.

Backfills three unique constraints:
  * ``oe_service_contract.contract_number``
  * ``oe_service_ticket (contract_id, ticket_number)`` (composite — ticket
    numbers reset per contract)
  * ``oe_service_work_order.work_order_number``

Uses ``op.create_index`` with ``unique=True`` so SQLite (no
``ALTER TABLE ADD CONSTRAINT``) succeeds.

Revision ID: v3101_svc
Revises: v3100_sched
Create Date: 2026-05-22
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3101_svc"
down_revision: Union[str, Sequence[str], None] = "v3100_sched"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, [cols], index_name)
_UNIQUES: list[tuple[str, list[str], str]] = [
    ("oe_service_contract", ["contract_number"], "uq_oe_service_contract_number"),
    (
        "oe_service_ticket",
        ["contract_id", "ticket_number"],
        "uq_oe_service_ticket_contract_number",
    ),
    ("oe_service_work_order", ["work_order_number"], "uq_oe_service_work_order_number"),
]


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def _has_columns(
    inspector: sa.engine.reflection.Inspector,
    table: str,
    cols: list[str],
) -> bool:
    if table not in inspector.get_table_names():
        return False
    present = {c["name"] for c in inspector.get_columns(table)}
    return all(c in present for c in cols)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, cols, name in _UNIQUES:
        if (
            table in inspector.get_table_names()
            and _has_columns(inspector, table, cols)
            and not _has_index(inspector, table, name)
        ):
            try:
                op.create_index(name, table, cols, unique=True)
            except sa.exc.IntegrityError:
                # Pre-existing duplicates would block the unique index.
                # Skip and let the operator resolve.
                pass


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, _cols, name in _UNIQUES:
        if _has_index(inspector, table, name):
            op.drop_index(name, table_name=table)
