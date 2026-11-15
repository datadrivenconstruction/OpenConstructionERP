# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""users: SSO subject unique per issuer, SAML assertion replay table

``oe_users_user.oidc_sub`` was unique on its own, so an identity was named by the subject alone
whatever provider issued it. The subject is now unique per ``(oidc_issuer, oidc_sub)`` and the
single-column index stays, non-unique. ``oe_users_saml_assertion`` records consumed SAML
assertion IDs until they expire.

Inspector-guarded, so a database whose tables ``Base.metadata.create_all`` already created is a
no-op.

Revision ID: vsso01_sso_issuer_scoped_subject
Revises: vsbfk01_spec_import_document_fk
Create Date: 2026-11-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vsso01_sso_issuer_scoped_subject"
down_revision: str | Sequence[str] | None = "vsbfk01_spec_import_document_fk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USER = "oe_users_user"
_ASSERTION = "oe_users_saml_assertion"
_SUB_IX = "ix_oe_users_user_oidc_sub"
_PAIR_UQ = "uq_oe_users_user_oidc_issuer_sub"
_TS = sa.DateTime(timezone=True)


def upgrade() -> None:
    """Scope the subject to its issuer and create the assertion table (idempotent)."""
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if _USER in tables:
        for uq in inspector.get_unique_constraints(_USER):
            if uq.get("column_names") == ["oidc_sub"] and uq.get("name"):
                op.drop_constraint(uq["name"], _USER, type_="unique")
        indexes = {ix["name"]: ix for ix in inspector.get_indexes(_USER)}
        sub_ix = indexes.get(_SUB_IX)
        if sub_ix is not None and sub_ix.get("unique"):
            op.drop_index(_SUB_IX, table_name=_USER)
            sub_ix = None
        if sub_ix is None:
            op.create_index(_SUB_IX, _USER, ["oidc_sub"])
        if _PAIR_UQ not in indexes:
            op.create_index(_PAIR_UQ, _USER, ["oidc_issuer", "oidc_sub"], unique=True)

    if _ASSERTION not in tables:
        op.create_table(
            _ASSERTION,
            sa.Column("id", sa.String(36), primary_key=True, nullable=False),
            sa.Column("created_at", _TS, nullable=False, server_default=sa.func.now()),
            sa.Column("updated_at", _TS, nullable=False, server_default=sa.func.now()),
            sa.Column("assertion_id", sa.String(255), nullable=False),
            sa.Column("expires_at", _TS, nullable=False),
        )
        op.create_index("ix_oe_users_saml_assertion_assertion_id", _ASSERTION, ["assertion_id"], unique=True)
        op.create_index("ix_oe_users_saml_assertion_expires_at", _ASSERTION, ["expires_at"])


def downgrade() -> None:
    """Drop the assertion table and the per-issuer index; the subject index stays non-unique."""
    inspector = sa.inspect(op.get_bind())
    tables = inspector.get_table_names()
    if _ASSERTION in tables:
        op.drop_table(_ASSERTION)
    if _USER in tables and _PAIR_UQ in {ix["name"] for ix in inspector.get_indexes(_USER)}:
        op.drop_index(_PAIR_UQ, table_name=_USER)
