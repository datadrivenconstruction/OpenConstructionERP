# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""perf: index the owner/tenancy columns that a page load actually filters on.

This migration MUST be RUN (``alembic upgrade``), not merely stamped
--------------------------------------------------------------------
Prod builds the schema with ``create_all`` plus ``alembic stamp <head>`` and
never walks the chain (``.claude/rules/env-config.md``, ``alembic/env.py``,
``app/core/alembic_version_table.py``). ``create_all`` decides table by table:
it skips a table that already exists and therefore never adds an index to one.
So on an install that is already running, NEITHER half of this change arrives
on its own - the model declaration is skipped with the table, and the stamp
marks this revision applied without executing it.

An existing database gets these seven indexes only when someone runs this
revision against it by hand. A fresh install gets them from ``create_all``,
which is why the model declaration stays: it is the only half a fresh install
ever sees, exactly as the migration is the only half an existing one can get.

Background
----------
An audit of every ownership-style column in the schema (project_id, user_id,
tenant_id, owner_id, created_by and the rest of that family) found 624 such
columns, 223 of them without an index usable for a filter on the column alone.
That number on its own is not actionable: 200 of the 223 are filtered by no
query anywhere in the codebase, and an index for a query nobody runs is dead
weight on every INSERT. Narrowing to columns that are both unindexed and
actually filtered left 22, and narrowing again to the ones a user waits on
left the seven indexes created here.

Note that a foreign key does not create an index in PostgreSQL. Two of the
columns below are FK columns that looked covered and were not.

What each one is for
--------------------
* ``ix_oe_bim_quantity_map_project_id`` and ``ix_oe_bim_quantity_map_org_id``
  - ``oe_bim_quantity_map`` carried no index of any kind. The BIM quantity
  rules page issues ``list_scoped`` on mount with no ``enabled`` guard and a
  limit of 500, filtering on project_id (plus the IS NULL global-template
  branch); ``list_active`` filters on both columns during element mapping.
* ``ix_oe_contacts_contact_created_by`` - the contacts scope clause is
  ``tenant_id = ? OR created_by = ?``. PostgreSQL can only combine an OR of
  two equality tests into a BitmapOr when both sides are indexed; tenant_id
  was, created_by was not, so the planner scanned the table for the whole
  clause. The contacts list loads at mount with a limit of 500.
* ``ix_oe_tasks_task_created_by`` - same shape, ``responsible_id = ? OR
  created_by = ?`` behind the my-tasks toggle.
* ``ix_oe_hse_advanced_ppe_issue_recipient_user_id`` and
  ``ix_oe_hse_advanced_certification_owner_user_id`` - both FK columns, both
  the only filter on their tab's list query.
* ``ix_oe_match_elements_template_created_by`` - the templates panel lists a
  non-admin's own rows with ``created_by = ?`` alone, which never touches the
  tenant index that class already declares.

Source of truth
---------------
The models were changed first; the index names and column lists below were
then read back out of ``Base.metadata`` rather than written by hand, so the
two cannot drift. All seven names are what the declarative naming convention
(``ix_%(column_0_label)s``) produces for ``index=True`` on those columns.

Safety
------
Matches the pattern the existing index migrations in this chain already use
(v3123_boq_fk_indexes, v3124_propdev_analytics_indexes,
v3189_takeoff_composite_idx): ``CREATE INDEX CONCURRENTLY`` inside an
``autocommit_block`` so a populated table is never taken under an ACCESS
EXCLUSIVE lock, guarded by an inspector check so re-running on a database
that already has the index (for instance one built by ``create_all``) is a
no-op.

Two things about CONCURRENTLY worth stating rather than leaving to be
discovered.

An interrupted concurrent build leaves an INVALID index behind in PostgreSQL.
Whether the guard below then skips that name or tries to recreate it depends
on how the SQLAlchemy inspector reports invalid indexes, which is not
something this migration can establish. Either way the fix is the same: find
it, drop it, re-run.

    SELECT i.relname FROM pg_class i
      JOIN pg_index ix ON ix.indexrelid = i.oid
     WHERE ix.indisvalid = false;
    DROP INDEX CONCURRENTLY <name>;

A run that fails partway leaves the indexes already built committed, because
each one is created in its own autocommit block, while the alembic version
stamp is not written. Re-running the migration is the recovery: the guard
skips whatever landed and creates the rest.

Revision ID: v44_owner_filter_indexes
Revises: v43_sub_rollup_links
Create Date: 2026-09-23
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v44_owner_filter_indexes"
down_revision: Union[str, Sequence[str], None] = "v43_sub_rollup_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table, index name, columns) - generated from Base.metadata after the model
# change, not hand-written. Ordered most-felt first, so an interrupted run has
# built the ones that matter most; see the note above on re-running.
_INDEXES: list[tuple[str, str, list[str]]] = [
    ("oe_bim_quantity_map", "ix_oe_bim_quantity_map_project_id", ["project_id"]),
    ("oe_bim_quantity_map", "ix_oe_bim_quantity_map_org_id", ["org_id"]),
    ("oe_contacts_contact", "ix_oe_contacts_contact_created_by", ["created_by"]),
    ("oe_tasks_task", "ix_oe_tasks_task_created_by", ["created_by"]),
    ("oe_hse_advanced_ppe_issue", "ix_oe_hse_advanced_ppe_issue_recipient_user_id", ["recipient_user_id"]),
    ("oe_hse_advanced_certification", "ix_oe_hse_advanced_certification_owner_user_id", ["owner_user_id"]),
    ("oe_match_elements_template", "ix_oe_match_elements_template_created_by", ["created_by"]),
]


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, name: str) -> bool:
    if table not in inspector.get_table_names():
        return False
    return name in {ix["name"] for ix in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_postgres = bind.dialect.name == "postgresql"

    for table, index_name, columns in _INDEXES:
        if table not in inspector.get_table_names():
            # A module whose tables have not been bootstrapped yet; the next
            # create_all pass builds the index from the model declaration.
            continue
        if _has_index(inspector, table, index_name):
            continue
        if is_postgres:
            # CREATE INDEX CONCURRENTLY cannot run inside a transaction block,
            # and env.py wraps every migration in one. autocommit_block commits
            # the migration transaction for the duration of the lock-free build
            # and resumes it afterwards for the version stamp.
            with op.get_context().autocommit_block():
                op.create_index(index_name, table, columns, postgresql_concurrently=True)
        else:
            op.create_index(index_name, table, columns)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    for table, index_name, *_ in reversed(_INDEXES):
        if not _has_index(inspector, table, index_name):
            continue
        op.drop_index(index_name, table_name=table)
