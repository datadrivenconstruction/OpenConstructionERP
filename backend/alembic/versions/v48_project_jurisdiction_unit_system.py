# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""projects - a stated jurisdiction and measurement system on the project.

Two nullable columns on ``oe_projects_project`` with no default: ``jurisdiction``
(an ISO 3166-1 country or an ISO 3166-2 subdivision such as ``US-CA``) and
``unit_system`` (``metric`` or ``imperial``). Both start empty and are never
filled from the country, so every consumer keeps the answer it derives from the
country until somebody sets one.

``unit_system`` is not new to every database. ``v3135_project_unit_system``
added it as ``VARCHAR(16) NOT NULL DEFAULT 'metric'`` and the model dropped it
later, so a database that walked the chain carries the column with ``'metric'``
on every row - a value no API, screen or import could ever have written. Kept,
it would turn every such project explicitly metric and start warning on the
imperial bills of United States projects, which is exactly what "empty keeps
today's behaviour" rules out. So on that database the column is relaxed to
nullable, its default dropped and the default's values cleared, in that order:
clearing before the NOT NULL is dropped fails on precisely the databases this
exists for.

The clearing is gated on the chain's ``'metric'`` default still being there.
The boot-path repair ``project_unit_system_chain_default`` drops that default
in the same breath as it clears the values, so a database the new version has
already booted on - where ``metric`` may now be somebody's choice - is left
alone if this revision is run by hand afterwards.

Inspector-guarded throughout, so an install whose schema came from
``create_all`` plus the boot heal reaches this revision and changes nothing.

Revision ID: v48_project_jurisdiction_unit_system
Revises: v47_subcontract_agreement_contract
Create Date: 2026-09-28
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Union

import sqlalchemy as sa
from alembic import op

revision: str = "v48_project_jurisdiction_unit_system"
down_revision: Union[str, Sequence[str], None] = "v47_subcontract_agreement_contract"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TABLE = "oe_projects_project"
_JURISDICTION = "jurisdiction"
_UNIT_SYSTEM = "unit_system"
_CHAIN_DEFAULT = "metric"


def _columns() -> dict[str, dict]:
    inspector = sa.inspect(op.get_bind())
    if _TABLE not in set(inspector.get_table_names()):
        return {}
    return {column["name"]: column for column in inspector.get_columns(_TABLE)}


def _carries_chain_default(column: dict) -> bool:
    return _CHAIN_DEFAULT in str(column.get("default") or "")


# data-rewrite-ack: table=oe_projects_project growth=tenure rows=one per project; only
# databases that walked v3135 hold the column, and only rows still carrying the value its
# default wrote are cleared, once.
# boot-repair: registry=project_unit_system_chain_default
def upgrade() -> None:
    columns = _columns()
    if not columns:
        # The projects table was never created here, so there is nothing to
        # extend; adding to an absent table would stop the upgrade.
        return
    if _JURISDICTION not in columns:
        op.add_column(_TABLE, sa.Column(_JURISDICTION, sa.String(length=6), nullable=True))
    if _UNIT_SYSTEM not in columns:
        op.add_column(_TABLE, sa.Column(_UNIT_SYSTEM, sa.String(length=16), nullable=True))
        return
    if not _carries_chain_default(columns[_UNIT_SYSTEM]):
        return
    op.alter_column(_TABLE, _UNIT_SYSTEM, existing_type=sa.String(length=16), nullable=True)
    op.alter_column(_TABLE, _UNIT_SYSTEM, existing_type=sa.String(length=16), server_default=None)
    op.execute(
        sa.text(f"UPDATE {_TABLE} SET {_UNIT_SYSTEM} = NULL WHERE {_UNIT_SYSTEM} = :chain").bindparams(
            chain=_CHAIN_DEFAULT
        )
    )


def downgrade() -> None:
    columns = _columns()
    if not columns:
        return
    if _JURISDICTION in columns:
        op.drop_column(_TABLE, _JURISDICTION)
    if _UNIT_SYSTEM in columns:
        # Back to the shape v3135 gave the column, which is what the revision
        # below this one expects to find.
        op.execute(
            sa.text(f"UPDATE {_TABLE} SET {_UNIT_SYSTEM} = :chain WHERE {_UNIT_SYSTEM} IS NULL").bindparams(
                chain=_CHAIN_DEFAULT
            )
        )
        op.alter_column(
            _TABLE,
            _UNIT_SYSTEM,
            existing_type=sa.String(length=16),
            server_default=_CHAIN_DEFAULT,
            nullable=False,
        )
