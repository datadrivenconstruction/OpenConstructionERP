# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""projects - the participant grant table ADR 006 describes.

One new table and nothing else. **No data rewrite lives here**, and unlike
``v3325_organization_tenancy`` there is no repair waiting to run either: a grant
is a decision somebody makes after this ships, not a fact about the rows an
install already holds, so there is nothing to backfill and nothing to record in
a ledger. What this revision owns is the schema the decision is written into,
and the downgrade that removes it.

``oe_projects_participant_grant`` is the edge
``Project -> Grant -> grantee Organization``: one row per company participating
in a project it does not own, with a scope, a status, an optional validity
window, and the author of the decision. ADR 006 records the design and the
owner's eight decisions; the ones that shaped this DDL are:

* **the grantee is an organization, never a user** (decision 8), so the column
  is a foreign key to ``oe_users_organization`` and there is no user-shaped
  alternative in the table for a caller to reach for;
* **a grant is unilateral** (decision 2), so ``status`` has no ``offered`` value
  and nothing in the schema waits for an acceptance that will never come;
* **the scope is ``view`` / ``contribute`` / ``manage``** (decision 7), held in
  a check constraint rather than left as a free string, because a value outside
  the vocabulary would be a grant no reader can interpret;
* **revocation is an event, not a deletion** (decisions 3 and the ADR's section
  8), so the revoked row stays and the uniqueness that keeps the live set
  unambiguous is a *partial* index over ``status <> 'revoked'``. Re-granting
  after a revocation inserts a new row, which is what makes the history
  reconstructible from this table alone;
* **a change of project ownership suspends the grants pending review**
  (decision 4), which needs to find every grant a company made, so
  ``granted_on_behalf_of_organization_id`` carries an index of its own.

It also owns the ADR's promise about the rest of the schema: **zero changes to
the 30 existing ``tenant_id`` columns.** A grant adds a table and, in stage 3, a
second GUC. It does not re-stamp a single row, because an unbounded rewrite of
30 columns across a populated install is exactly what Phase 02b spent its effort
making unnecessary.

Names are spelled out rather than left to the naming convention in
``app.database``, and every one of them is under PostgreSQL's 63-character
identifier limit (``tests/unit/test_migration_identifier_length.py`` scans for
that). This product does not run ``alembic upgrade head`` against an existing
database - ``postgres_auto_migrate`` creates missing tables and then stamps head
- so a database built by this revision and one built by ``create_all`` have to be
indistinguishable, and they can only be if both sides write the same identifier.
Two of them could not be left to the convention at all: ``ix_%(column_0_label)s``
over ``granted_on_behalf_of_organization_id`` resolves to 69 characters, and
``fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s`` over the same
column resolves to 91.

The three check constraints are the opposite case and are the reason this file
carries two names for each of them. The convention is
``ck_%(table_name)s_%(constraint_name)s``, and a convention that names
``%(constraint_name)s`` is applied to a constraint that already has a name - so
what the database stores is the model's name with the table wrapped around it,
60 characters, which is the same string ``_effective_name`` in
``app.core.postgres_migrator`` computes. An operation in this file is therefore
given the model's own short name and lets ``alembic/env.py``'s
``target_metadata`` wrap it exactly as ``create_all`` does; only the catalog
comparison uses the stored form. Writing the stored form into an operation wraps
it twice, to 93 characters, and PostgreSQL does not store that as written:
SQLAlchemy hash-mangles it, and the revision then creates a constraint whose
name exists in no other installation and which the boot heal cannot match. That
is not a hypothetical - it is what the first draft of this file did, and
``tests/integration/test_migrations_roundtrip.py`` refused it on the downgrade
step, naming the mangled identifier in the error.

Two more names are spelled out because ``create_all`` does not stop at what the
model declares. ``app.database`` imports :mod:`app.core.pg_optimizations`, whose
``after_create`` handler adds a btree index to every foreign-key column that is
not already the left-most column of an index, and a composite
``(project_id, created_at)`` and ``(project_id, status)`` index to any table
carrying both columns. This table qualifies for four of them, so the revision
creates the same four under the same names - ``_index_name`` in that module is
the scheme, and the names are written down here rather than imported from it
because a revision is frozen history. What keeps them from drifting is a test
rather than a shared constant:
``tests/pg/test_the_participant_grant_table_is_the_same_however_it_was_built.py``
snapshots the catalog ``create_all`` built, drops the table, lets this revision
rebuild it, and compares the two snapshots index definitions and constraint
definitions included. If that module's rule changes, the comparison names the
difference instead of an installation discovering it as a missing index.

Every step is inspector-guarded, so a database whose tables ``create_all``
already built reaches this revision and does nothing.

Revision ID: v3326_project_participant_grant
Revises: v3325_organization_tenancy
Create Date: 2026-11-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v3326_project_participant_grant"
down_revision: str | Sequence[str] | None = "v3325_organization_tenancy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GRANT = "oe_projects_participant_grant"
_PROJECT = "oe_projects_project"
_ORGANIZATION = "oe_users_organization"
_USER = "oe_users_user"

# The three check constraints, as SQL and as two names each.
#
# ``_CK_*`` is the name the model declares and the name every alembic operation
# in this file is given. ``_CK_*_STORED`` is the name the database holds, which
# is the declared name with the table wrapped around it, because the convention
# in ``app.database`` is ``ck_%(table_name)s_%(constraint_name)s`` and a
# convention carrying ``%(constraint_name)s`` is applied to a constraint that
# already has a name. Only the inspector is compared against the stored form:
# handing it to ``op.create_check_constraint`` or ``op.drop_constraint`` would
# wrap it a second time, to 93 characters, which PostgreSQL will not store as
# written and SQLAlchemy then hash-mangles - a name that exists in no other
# installation, and one the boot heal cannot match.
#
# ``alembic/env.py`` sets ``target_metadata = Base.metadata``, so the convention
# is in force for every operation below, which is what makes declaring the
# model's own name here produce the model's own stored name. This is the pattern
# ``v3298_teams_roster`` set for ``ck_teams_roster_single_link``.
_WINDOW_SQL = "valid_from IS NULL OR valid_until IS NULL OR valid_until > valid_from"
_SCOPE_SQL = "scope IN ('view', 'contribute', 'manage')"
_STATUS_SQL = "status IN ('active', 'suspended', 'revoked')"
_CK_WINDOW = "ck_participant_grant_window"
_CK_SCOPE = "ck_participant_grant_scope"
_CK_STATUS = "ck_participant_grant_status"
_CK_WINDOW_STORED = "ck_oe_projects_participant_grant_ck_participant_grant_window"
_CK_SCOPE_STORED = "ck_oe_projects_participant_grant_ck_participant_grant_scope"
_CK_STATUS_STORED = "ck_oe_projects_participant_grant_ck_participant_grant_status"

#: The primary key is named because PostgreSQL would otherwise call it
#: ``oe_projects_participant_grant_pkey`` here and ``pk_oe_projects_participant_grant``
#: on an install built by ``create_all``, where the metadata naming convention in
#: ``app.database`` supplies the name. Same constraint, two catalogs, and the
#: boot heal compares names.
_PK = "pk_oe_projects_participant_grant"

_IX_PROJECT = "ix_projects_participant_grant_project"
_IX_GRANTEE = "ix_projects_participant_grant_grantee"
_IX_ON_BEHALF = "ix_projects_participant_grant_on_behalf"
#: Partial and unique: one LIVE grant per company per project. An index rather
#: than a unique constraint because a ``WHERE`` clause can only be expressed as
#: one, and because ``create_all`` builds it as an index too - a constraint here
#: would leave the two install shapes disagreeing in ``pg_constraint``.
_UQ_LIVE = "uq_projects_participant_grant_live"
_UQ_LIVE_WHERE = "status <> 'revoked'"

#: The four indexes ``app.core.pg_optimizations._desired_indexes`` adds to this
#: table on ``create_all``, named by that module's ``_index_name`` scheme. Two
#: are the foreign-key columns no declared index leads with; two are the
#: composite hot paths a table carrying both ``project_id`` and ``created_at``
#: (and ``status``) always gets.
_IX_FK_GRANTED_BY = "ix_oe_projects_participant_grant_granted_by_user_id"
_IX_FK_REVOKED_BY = "ix_oe_projects_participant_grant_revoked_by_user_id"
_IX_PROJECT_CREATED = "ix_oe_projects_participant_grant_project_id_created_at"
_IX_PROJECT_STATUS = "ix_oe_projects_participant_grant_project_id_status"

_FK_PROJECT = "fk_projects_participant_grant_project"
_FK_GRANTEE = "fk_projects_participant_grant_grantee"
_FK_GRANTED_BY = "fk_projects_participant_grant_granted_by"
_FK_ON_BEHALF = "fk_projects_participant_grant_on_behalf"
_FK_REVOKED_BY = "fk_projects_participant_grant_revoked_by"


def _tables(bind) -> set[str]:
    return set(sa.inspect(bind).get_table_names())


def _columns(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _indexes(bind, table: str) -> set[str]:
    return {i["name"] for i in sa.inspect(bind).get_indexes(table)}


def _check_constraints(bind, table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(bind).get_check_constraints(table)}


def _foreign_keys(bind, table: str) -> set[str]:
    return {f["name"] for f in sa.inspect(bind).get_foreign_keys(table)}


def upgrade() -> None:
    """Create the grant table when it is missing. Additive; no data rewrite."""
    bind = op.get_bind()
    tables = _tables(bind)
    supports_fk = bind.dialect.name != "sqlite"

    if _GRANT not in tables:
        op.create_table(
            _GRANT,
            sa.Column("id", GUID(), nullable=False),
            sa.Column("project_id", GUID(), nullable=False),
            sa.Column("grantee_organization_id", GUID(), nullable=False),
            # The person who decided. ``SET NULL`` below, so deleting a user
            # never deletes the record that a company was given access.
            sa.Column("granted_by_user_id", GUID(), nullable=True),
            sa.Column("granted_on_behalf_of_organization_id", GUID(), nullable=False),
            # No server_default on ``scope`` or ``status``, because the model
            # declares a Python-side default only. A default here and not there
            # would be a difference the next autogenerated diff reports, and the
            # point of spelling the names out above is that there is no such
            # difference to find.
            sa.Column("scope", sa.String(32), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
            sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("revoked_by_user_id", GUID(), nullable=True),
            sa.Column("revocation_reason", sa.String(500), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.CheckConstraint(_WINDOW_SQL, name=_CK_WINDOW),
            sa.CheckConstraint(_SCOPE_SQL, name=_CK_SCOPE),
            sa.CheckConstraint(_STATUS_SQL, name=_CK_STATUS),
            sa.PrimaryKeyConstraint("id", name=_PK),
        )
        tables.add(_GRANT)

    indexes = _indexes(bind, _GRANT)
    if _IX_PROJECT not in indexes:
        op.create_index(_IX_PROJECT, _GRANT, ["project_id"])
    if _IX_GRANTEE not in indexes:
        op.create_index(_IX_GRANTEE, _GRANT, ["grantee_organization_id"])
    if _IX_ON_BEHALF not in indexes:
        op.create_index(_IX_ON_BEHALF, _GRANT, ["granted_on_behalf_of_organization_id"])
    if _UQ_LIVE not in indexes:
        op.create_index(
            _UQ_LIVE,
            _GRANT,
            ["project_id", "grantee_organization_id"],
            unique=True,
            postgresql_where=sa.text(_UQ_LIVE_WHERE),
        )
    # The four ``create_all`` adds through ``pg_optimizations``. Guarded by name
    # like the rest, so an install that already has them - which is every install
    # this product has, because ``create_all`` is what builds its tables - gets
    # nothing here.
    if _IX_FK_GRANTED_BY not in indexes:
        op.create_index(_IX_FK_GRANTED_BY, _GRANT, ["granted_by_user_id"])
    if _IX_FK_REVOKED_BY not in indexes:
        op.create_index(_IX_FK_REVOKED_BY, _GRANT, ["revoked_by_user_id"])
    if _IX_PROJECT_CREATED not in indexes:
        op.create_index(_IX_PROJECT_CREATED, _GRANT, ["project_id", "created_at"])
    if _IX_PROJECT_STATUS not in indexes:
        op.create_index(_IX_PROJECT_STATUS, _GRANT, ["project_id", "status"])

    if supports_fk:
        existing = _foreign_keys(bind, _GRANT)
        # A grant on a deleted project is a statement about nothing. Projects are
        # archived rather than deleted in the ordinary course, so this fires on a
        # purge and not on something a user does by accident.
        if _PROJECT in tables and _FK_PROJECT not in existing:
            op.create_foreign_key(_FK_PROJECT, _GRANT, _PROJECT, ["project_id"], ["id"], ondelete="CASCADE")
        if _ORGANIZATION in tables and _FK_GRANTEE not in existing:
            op.create_foreign_key(
                _FK_GRANTEE, _GRANT, _ORGANIZATION, ["grantee_organization_id"], ["id"], ondelete="CASCADE"
            )
        if _USER in tables and _FK_GRANTED_BY not in existing:
            op.create_foreign_key(_FK_GRANTED_BY, _GRANT, _USER, ["granted_by_user_id"], ["id"], ondelete="SET NULL")
        if _ORGANIZATION in tables and _FK_ON_BEHALF not in existing:
            op.create_foreign_key(
                _FK_ON_BEHALF,
                _GRANT,
                _ORGANIZATION,
                ["granted_on_behalf_of_organization_id"],
                ["id"],
                ondelete="CASCADE",
            )
        if _USER in tables and _FK_REVOKED_BY not in existing:
            op.create_foreign_key(_FK_REVOKED_BY, _GRANT, _USER, ["revoked_by_user_id"], ["id"], ondelete="SET NULL")

    # Guarded separately from the table creation: an install whose table arrived
    # through ``create_all`` in a release before the check constraints were
    # declared reaches this revision with the table present and still has to be
    # given them. The columns are checked too, because a check constraint naming
    # a column that is not there yet is a statement that fails the whole
    # revision, and PostgreSQL runs DDL in a transaction - one refusal here costs
    # an install every pending revision rather than this one.
    columns = _columns(bind, _GRANT)
    if {"valid_from", "valid_until"} <= columns:
        checks = _check_constraints(bind, _GRANT)
        for declared, stored, sql, column in (
            (_CK_WINDOW, _CK_WINDOW_STORED, _WINDOW_SQL, "valid_until"),
            (_CK_SCOPE, _CK_SCOPE_STORED, _SCOPE_SQL, "scope"),
            (_CK_STATUS, _CK_STATUS_STORED, _STATUS_SQL, "status"),
        ):
            if stored not in checks and column in columns:
                op.create_check_constraint(declared, _GRANT, sa.text(sql))


def downgrade() -> None:
    """Remove the grant table.

    The grant rows go with it, and that is the named limit of this downgrade
    rather than something discovered by whoever runs it. There is no ledger to
    replay because nothing was rewritten on the way up: the table is the data.
    What survives is the audit trail - every create, scope change, suspension and
    revocation writes an ``oe_activity_log`` row (ADR 006 section 8), and that
    table is untouched here - so "who could see this project on that date" stays
    answerable after the downgrade and re-granting is a reconstruction from a
    record rather than a guess.

    Constraints and indexes are dropped before the table they belong to, and the
    foreign keys are dropped by name rather than left to ``DROP TABLE``: a
    database that reached this revision through ``create_all`` has them under
    exactly these names, and a downgrade that depends on the cascade behaviour of
    a dialect is a downgrade that behaves differently per install.
    """
    bind = op.get_bind()
    if _GRANT not in _tables(bind):
        return
    supports_fk = bind.dialect.name != "sqlite"

    if supports_fk:
        existing = _foreign_keys(bind, _GRANT)
        for name in (_FK_PROJECT, _FK_GRANTEE, _FK_GRANTED_BY, _FK_ON_BEHALF, _FK_REVOKED_BY):
            if name in existing:
                op.drop_constraint(name, _GRANT, type_="foreignkey")

    checks = _check_constraints(bind, _GRANT)
    for declared, stored in (
        (_CK_WINDOW, _CK_WINDOW_STORED),
        (_CK_SCOPE, _CK_SCOPE_STORED),
        (_CK_STATUS, _CK_STATUS_STORED),
    ):
        if stored in checks:
            op.drop_constraint(declared, _GRANT, type_="check")

    indexes = _indexes(bind, _GRANT)
    for name in (
        _UQ_LIVE,
        _IX_PROJECT,
        _IX_GRANTEE,
        _IX_ON_BEHALF,
        _IX_FK_GRANTED_BY,
        _IX_FK_REVOKED_BY,
        _IX_PROJECT_CREATED,
        _IX_PROJECT_STATUS,
    ):
        if name in indexes:
            op.drop_index(name, table_name=_GRANT)

    op.drop_table(_GRANT)
