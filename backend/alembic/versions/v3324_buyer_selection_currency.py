# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""property_dev: a buyer's option selection says what money it is in

Adds ``currency`` to ``oe_property_dev_buyer_selection`` and
``oe_property_dev_buyer_selection_item``.

A selection's ``total_options_value`` is the sum of its lines, and each line
copies an option's ``price_delta`` into ``unit_price_snapshot`` at the moment
it is added. Options carry a currency; the selection and its lines carried
none. So a kitchen upgrade quoted in euros and a flooring upgrade quoted in
dollars added into one total that is money in neither, and nothing on the
row or on the wire could say so. This is the shape ``v3304`` closed for stock
cost, where a weighted average rolled two currencies into one number: give
the figure a label, and refuse to blend where the label disagrees.

Both columns are ``String(8) NOT NULL DEFAULT ''``, the shape every other
money row in this module carries its currency in. The empty string is this
module's "not stamped" value (see ``Development.currency`` in models.py,
where it means "read the parent's currency at read time"), so it is what an
unresolvable row is left at, rather than NULL, which no other currency column
in the module uses and which ``_currency_code`` would only fold back to blank.

Backfill, all of it idempotent and confined to rows still blank:

1. A line takes its option's currency, else the option's development's, else
   that development's project's. The option is the source because the line's
   price was copied from the option's ``price_delta``, so it is denominated
   in whatever the option was.
2. A selection takes its buyer's currency (the contract is signed in it),
   else the buyer's plot's, else the development's, else the project's.
3. A selection still blank after that adopts the one currency its lines
   agree on, if they agree on exactly one. A blank line is not a currency
   and does not count as agreement.

A line whose currency disagrees with its selection's after all three steps
is left as it stands and counted in the summary. That is a real mixed
selection, and folding one side into the other would be the blend this
revision exists to stop; the application refuses to create new ones.

The DDL is inspector-guarded the way this tree guards ``add_column``, for the
usual reason: the boot path runs ``Base.metadata.create_all`` before anybody
can run ``alembic upgrade head``, so on a real install the columns already
exist and an unguarded ADD COLUMN raises DuplicateColumn and takes every
later revision with it. The backfill is NOT guarded on the column existing,
because an existing column says nothing about whether the rows were ever
labelled: ``create_all`` makes the column and fills nothing.

Revision ID: v3324_buyer_selection_currency
Revises: v3323_broker_license_unique_without_tenant
Create Date: 2026-09-08
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3324_buyer_selection_currency"
down_revision: Union[str, Sequence[str], None] = "v3323_broker_license_unique_without_tenant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Kept in step with app/modules/property_dev/models.py and
# app/modules/projects/models.py. Repeated as literals rather than imported
# because a migration has to keep meaning what it meant on the day it ran.
_SELECTION = "oe_property_dev_buyer_selection"
_ITEM = "oe_property_dev_buyer_selection_item"
_OPTION = "oe_property_dev_buyer_option"
_GROUP = "oe_property_dev_buyer_option_group"
_BUYER = "oe_property_dev_buyer"
_PLOT = "oe_property_dev_plot"
_DEVELOPMENT = "oe_property_dev_development"
_PROJECT = "oe_projects_project"
COLUMN = "currency"

# Step 1. Every id in this module is app.database.GUID, VARCHAR(36) on every
# dialect, so the joins compare text with text.
_BACKFILL_ITEMS_SQL = f"""
UPDATE {_ITEM} AS item
SET currency = src.code
FROM (
    SELECT opt.id AS option_id,
           COALESCE(NULLIF(UPPER(TRIM(opt.currency)), ''),
                    NULLIF(UPPER(TRIM(dev.currency)), ''),
                    NULLIF(UPPER(TRIM(proj.currency)), '')) AS code
    FROM {_OPTION} AS opt
    JOIN {_GROUP} AS grp ON grp.id = opt.group_id
    JOIN {_DEVELOPMENT} AS dev ON dev.id = grp.development_id
    LEFT JOIN {_PROJECT} AS proj ON proj.id = dev.project_id
) AS src
WHERE item.option_id = src.option_id
  AND item.currency = ''
  AND src.code IS NOT NULL
"""

# Step 2.
_BACKFILL_SELECTIONS_FROM_BUYER_SQL = f"""
UPDATE {_SELECTION} AS sel
SET currency = src.code
FROM (
    SELECT b.id AS buyer_id,
           COALESCE(NULLIF(UPPER(TRIM(b.currency)), ''),
                    NULLIF(UPPER(TRIM(p.currency)), ''),
                    NULLIF(UPPER(TRIM(dev.currency)), ''),
                    NULLIF(UPPER(TRIM(proj.currency)), '')) AS code
    FROM {_BUYER} AS b
    LEFT JOIN {_PLOT} AS p ON p.id = b.plot_id
    JOIN {_DEVELOPMENT} AS dev ON dev.id = b.development_id
    LEFT JOIN {_PROJECT} AS proj ON proj.id = dev.project_id
) AS src
WHERE sel.buyer_id = src.buyer_id
  AND sel.currency = ''
  AND src.code IS NOT NULL
"""

# Step 3. MIN over a group that HAVING has already held to one distinct
# value is that value; it is not a choice between two.
_BACKFILL_SELECTIONS_FROM_ITEMS_SQL = f"""
UPDATE {_SELECTION} AS sel
SET currency = src.code
FROM (
    SELECT selection_id, MIN(currency) AS code
    FROM {_ITEM}
    WHERE currency <> ''
    GROUP BY selection_id
    HAVING COUNT(DISTINCT currency) = 1
) AS src
WHERE sel.id = src.selection_id
  AND sel.currency = ''
"""

# Reported, never rewritten: lines that disagree with their selection.
_COUNT_DISAGREEMENTS_SQL = f"""
SELECT COUNT(*)
FROM {_ITEM} AS item
JOIN {_SELECTION} AS sel ON sel.id = item.selection_id
WHERE item.currency <> ''
  AND sel.currency <> ''
  AND item.currency <> sel.currency
"""

# Two literals rather than one template: the data-rewrite gate resolves a
# table by reading the statement where it is executed, and a ``.format`` call
# between the constant and the text would leave both counts unresolvable.
_COUNT_BLANK_ITEMS_SQL = f"SELECT COUNT(*) FROM {_ITEM} WHERE currency = ''"
_COUNT_BLANK_SELECTIONS_SQL = f"SELECT COUNT(*) FROM {_SELECTION} WHERE currency = ''"


def _has_table(insp: sa.engine.reflection.Inspector, table: str) -> bool:
    return table in insp.get_table_names()


def _has_column(insp: sa.engine.reflection.Inspector, table: str, column: str) -> bool:
    if not _has_table(insp, table):
        return False
    return any(col["name"] == column for col in insp.get_columns(table))


def _add_currency(insp: sa.engine.reflection.Inspector, table: str) -> None:
    if _has_column(insp, table, COLUMN):
        return
    # String(8) with a server default of '', the type and default the model
    # declares, so a fresh volume built by ``create_all`` and an upgraded one
    # end up with one schema. NOT NULL is safe with the default in the same
    # statement: every existing row takes ''.
    op.add_column(table, sa.Column(COLUMN, sa.String(length=8), nullable=False, server_default=""))


# data-rewrite-ack: table=oe_property_dev_buyer_selection_item growth=tenure rows=one per option a buyer picked, a handful per sold unit, kept for the life of the development and never deleted once locked; small on every demo box and a few thousand on a developer selling for years, and each row is short
# data-rewrite-ack: table=oe_property_dev_buyer_selection growth=tenure rows=one or a few per buyer, so it follows units sold rather than time directly, but units sold accumulate for as long as the install trades; hundreds to low thousands on a mature install
# boot-repair: gap - the product never runs `alembic upgrade`; the boot heal adds both `currency` columns with their '' server default and writes no rows, so on an ordinary upgraded install the three labelling statements above do not run and every selection and line from before this revision stays at ''. The read side already tolerates that: the sales UI prints a selection's total in the buyer's currency when the selection carries none, and the service settles a blank selection from the first stamped line added to it, so a legacy draft is labelled the moment it is touched. A locked legacy selection stays unlabelled; no registry repair is proposed here because deciding whether the label may be written onto a locked, contracted document is the founder's call, not a boot-time one.
def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if not _has_table(insp, _SELECTION) or not _has_table(insp, _ITEM):
        return
    _add_currency(insp, _SELECTION)
    _add_currency(insp, _ITEM)

    # The labelling is deliberately not behind the column guard above: on the
    # default runtime the columns arrive through create_all, empty, and an
    # install that got here that way needs this pass more than a fresh one.
    # Every statement touches only rows still blank, so running it twice is
    # running it once.
    blank_items_before = bind.execute(sa.text(_COUNT_BLANK_ITEMS_SQL)).scalar_one()
    blank_selections_before = bind.execute(sa.text(_COUNT_BLANK_SELECTIONS_SQL)).scalar_one()
    bind.execute(sa.text(_BACKFILL_ITEMS_SQL))
    bind.execute(sa.text(_BACKFILL_SELECTIONS_FROM_BUYER_SQL))
    bind.execute(sa.text(_BACKFILL_SELECTIONS_FROM_ITEMS_SQL))
    blank_items_after = bind.execute(sa.text(_COUNT_BLANK_ITEMS_SQL)).scalar_one()
    blank_selections_after = bind.execute(sa.text(_COUNT_BLANK_SELECTIONS_SQL)).scalar_one()
    disagreements = bind.execute(sa.text(_COUNT_DISAGREEMENTS_SQL)).scalar_one()
    print(
        f"v3324 buyer selection currency: "
        f"{blank_items_before - blank_items_after} of {blank_items_before} unlabelled lines labelled; "
        f"{blank_selections_before - blank_selections_after} of {blank_selections_before} unlabelled selections "
        f"labelled; lines that disagree with their selection and were left as they stand: {disagreements}"
    )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    if _has_column(insp, _ITEM, COLUMN):
        op.drop_column(_ITEM, COLUMN)
    if _has_column(insp, _SELECTION, COLUMN):
        op.drop_column(_SELECTION, COLUMN)
