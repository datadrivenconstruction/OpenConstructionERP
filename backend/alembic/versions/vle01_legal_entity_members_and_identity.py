# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""legal entity members, seller identity and project site

Additive only, so a deploy that heals its schema at boot picks it up without
``alembic upgrade``:

* ``oe_legal_entities_member``: who works for which entity, with a role;
* ``oe_legal_entities_entity``: ``legal_name``, ``address``, ``tax_ids``
  (list of ``{scheme, value}``), ``invoice_prefix``;
* ``oe_legal_entities_branch.address``: where the site is;
* ``oe_projects_project.legal_entity_branch_id``: the site the project runs from.

No data is moved. An existing install has no members, and a person with no
membership sees exactly the projects they saw before; a project that names no
entity keeps falling back to the default one, so its documents do not change.

Revision ID: vle01_legal_entity_members_and_identity
Revises: vfwk01_framework_agreements
Create Date: 2026-11-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vle01_legal_entity_members_and_identity"
down_revision: str | Sequence[str] | None = "vfwk01_framework_agreements"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ENTITY = "oe_legal_entities_entity"
_BRANCH = "oe_legal_entities_branch"
_MEMBER = "oe_legal_entities_member"
_PROJECT = "oe_projects_project"
_MEMBER_USER_INDEX = "ix_oe_legal_entities_member_user"
_ENTITY_COLUMNS = ("legal_name", "address", "tax_ids", "invoice_prefix")
_PROJECT_COLUMN = "legal_entity_branch_id"


def _columns(table: str) -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table)}


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    # ``String(36)``: GUID is a TypeDecorator over String(36), the type create_all builds.
    guid = sa.String(36)

    if inspector.has_table(_ENTITY):
        have = _columns(_ENTITY)
        if "legal_name" not in have:
            op.add_column(_ENTITY, sa.Column("legal_name", sa.String(255), nullable=True))
        if "address" not in have:
            op.add_column(_ENTITY, sa.Column("address", sa.JSON(), nullable=True))
        if "tax_ids" not in have:
            op.add_column(_ENTITY, sa.Column("tax_ids", sa.JSON(), nullable=False, server_default=sa.text("'[]'")))
        if "invoice_prefix" not in have:
            op.add_column(_ENTITY, sa.Column("invoice_prefix", sa.String(32), nullable=True))

        if not inspector.has_table(_MEMBER):
            op.create_table(
                _MEMBER,
                sa.Column("id", guid, primary_key=True),
                sa.Column(
                    "created_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                    nullable=False,
                ),
                sa.Column(
                    "updated_at",
                    sa.DateTime(timezone=True),
                    server_default=sa.text("CURRENT_TIMESTAMP"),
                    nullable=False,
                ),
                sa.Column("legal_entity_id", guid, sa.ForeignKey(f"{_ENTITY}.id", ondelete="CASCADE"), nullable=False),
                sa.Column("user_id", guid, sa.ForeignKey("oe_users_user.id", ondelete="CASCADE"), nullable=False),
                sa.Column("role", sa.String(16), nullable=False, server_default="member"),
                sa.UniqueConstraint("legal_entity_id", "user_id", name="uq_oe_legal_entities_member_entity_user"),
            )
        if inspector.has_table(_BRANCH) and "address" not in _columns(_BRANCH):
            op.add_column(_BRANCH, sa.Column("address", sa.JSON(), nullable=True))
        if _MEMBER_USER_INDEX not in {ix["name"] for ix in sa.inspect(op.get_bind()).get_indexes(_MEMBER)}:
            op.create_index(_MEMBER_USER_INDEX, _MEMBER, ["user_id"])

    if inspector.has_table(_PROJECT) and _PROJECT_COLUMN not in _columns(_PROJECT):
        op.add_column(_PROJECT, sa.Column(_PROJECT_COLUMN, guid, nullable=True))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if inspector.has_table(_PROJECT) and _PROJECT_COLUMN in _columns(_PROJECT):
        op.drop_column(_PROJECT, _PROJECT_COLUMN)
    if inspector.has_table(_MEMBER):
        op.drop_table(_MEMBER)
    if inspector.has_table(_BRANCH) and "address" in _columns(_BRANCH):
        op.drop_column(_BRANCH, "address")
    if inspector.has_table(_ENTITY):
        have = _columns(_ENTITY)
        for name in _ENTITY_COLUMNS:
            if name in have:
                op.drop_column(_ENTITY, name)
