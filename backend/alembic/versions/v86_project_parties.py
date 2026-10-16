# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""teams - project parties and party visibility in the shared registers.

Creates three tables and touches no existing one:

    oe_teams_project_party - a company on a project, in a role
    oe_teams_party_member  - which party a project member belongs to
    oe_teams_party_record  - which parties hold a record of a shared register

``oe_teams_party_member`` carries ``project_id`` next to ``party_id`` so the
unique constraint on ``(project_id, user_id)`` can hold "a member has at most
one party per project" in the database. ``oe_teams_party_record`` allows one
``originator`` row per record through a partial unique index.

A project without parties gains no rows, so existing projects read exactly as
before. Safe on a populated database: three CREATE TABLE and their indexes on
tables that did not exist. Every step is inspector-guarded, so a database whose
tables ``create_all`` already built reaches this revision and does nothing.

Revision ID: v86_project_parties
Revises: v82_requisition_item_sources
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "v86_project_parties"
down_revision: str | Sequence[str] | None = "v82_requisition_item_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PARTY = "oe_teams_project_party"
_MEMBER = "oe_teams_party_member"
_RECORD = "oe_teams_party_record"

# ``GUID`` renders as String(36) on every dialect.
_GUID = sa.String(36)
_TS = sa.DateTime(timezone=True)


def _base_columns() -> list[sa.Column]:
    return [
        sa.Column("id", _GUID, primary_key=True, nullable=False),
        sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", _TS, nullable=False, server_default=sa.func.now()),
    ]


def _project_fk() -> sa.Column:
    return sa.Column(
        "project_id",
        _GUID,
        sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )


def _party_fk() -> sa.Column:
    return sa.Column("party_id", _GUID, sa.ForeignKey(f"{_PARTY}.id", ondelete="CASCADE"), nullable=False)


def _ensure_indexes(table: str, wanted: list[tuple[str, list[str], dict]]) -> None:
    existing = {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(table)}
    for name, cols, kwargs in wanted:
        if name not in existing:
            op.create_index(name, table, cols, **kwargs)


def upgrade() -> None:
    """Create the three party tables and their indexes, each only when missing."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if _PARTY not in tables:
        op.create_table(
            _PARTY,
            *_base_columns(),
            _project_fk(),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("role", sa.String(32), nullable=False, server_default="subcontractor"),
            sa.Column("legal_entity_id", _GUID, nullable=True),
            sa.Column("contact_id", _GUID, nullable=True),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        )
    _ensure_indexes(
        _PARTY,
        [
            ("ix_oe_teams_project_party_project_id", ["project_id"], {}),
            ("ix_teams_project_party_project_active", ["project_id", "is_active"], {}),
        ],
    )
    if _MEMBER not in tables:
        op.create_table(
            _MEMBER,
            *_base_columns(),
            _project_fk(),
            _party_fk(),
            sa.Column("user_id", _GUID, sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"), nullable=False),
            sa.UniqueConstraint("project_id", "user_id", name="uq_teams_party_member_project_user"),
        )
    _ensure_indexes(
        _MEMBER,
        [
            ("ix_oe_teams_party_member_project_id", ["project_id"], {}),
            ("ix_oe_teams_party_member_party_id", ["party_id"], {}),
            ("ix_oe_teams_party_member_user_id", ["user_id"], {}),
        ],
    )
    if _RECORD not in tables:
        op.create_table(
            _RECORD,
            *_base_columns(),
            _project_fk(),
            sa.Column("entity_type", sa.String(64), nullable=False),
            sa.Column("entity_id", _GUID, nullable=False),
            _party_fk(),
            sa.Column("access", sa.String(16), nullable=False, server_default="shared"),
            sa.Column("permission", sa.String(16), nullable=False, server_default="view"),
            sa.Column("shared_by", _GUID, nullable=True),
            sa.UniqueConstraint("entity_type", "entity_id", "party_id", name="uq_teams_party_record_entity_party"),
        )
    _ensure_indexes(
        _RECORD,
        [
            ("ix_oe_teams_party_record_project_id", ["project_id"], {}),
            ("ix_teams_party_record_party_type", ["party_id", "entity_type"], {}),
            ("ix_teams_party_record_entity", ["entity_type", "entity_id"], {}),
            (
                "uq_teams_party_record_originator",
                ["entity_type", "entity_id"],
                {
                    "unique": True,
                    "postgresql_where": sa.text("access = 'originator'"),
                    "sqlite_where": sa.text("access = 'originator'"),
                },
            ),
        ],
    )


def downgrade() -> None:
    """Drop the three party tables, children first."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for name in (_RECORD, _MEMBER, _PARTY):
        if name in tables:
            op.drop_table(name)
