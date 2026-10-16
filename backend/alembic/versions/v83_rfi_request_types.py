# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""rfi - request types as data.

One column is added to an existing table: ``oe_rfi_rfi.request_type``, ``VARCHAR(32) NOT NULL DEFAULT
'RFI'``, with the index ``ix_rfi_project_request_type`` on ``(project_id, request_type)``. Every RFI written
before types existed was an RFI, so the column default is the whole backfill: PostgreSQL fills the existing
rows with it as part of ``ADD COLUMN``. No row is rewritten by an UPDATE, which matters because revision bodies
do not run on an installed base; the boot heal adds the same column from the model with the same literal
default and reaches the same rows the same way.

One new table, ``oe_rfi_request_type``: a project's catalogue of request types (code, name per language,
numbering prefix and digits, response SLA, required fields, default approval route, preset of origin). Codes
and prefixes are unique per project. Rows cascade with their project.

Every constraint and index name is written out and matches the models. Every step is inspector-guarded, so a
database whose tables ``create_all`` already built reaches this revision and does nothing.

Revision ID: v83_rfi_request_types
Revises: v82_requisition_item_sources
Create Date: 2026-10-16
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v83_rfi_request_types"
down_revision: str | Sequence[str] | None = "v82_requisition_item_sources"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RFI_TABLE = "oe_rfi_rfi"
_RFI_INDEX = "ix_rfi_project_request_type"
_TYPE_TABLE = "oe_rfi_request_type"
_TYPE_INDEX = "ix_oe_rfi_request_type_project_id"


def upgrade() -> None:
    """Add the type column to requests, then the type catalogue table; each only when missing."""
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if _RFI_TABLE in tables:
        if "request_type" not in {c["name"] for c in sa.inspect(bind).get_columns(_RFI_TABLE)}:
            op.add_column(
                _RFI_TABLE,
                sa.Column("request_type", sa.String(length=32), nullable=False, server_default="RFI"),
            )
        if _RFI_INDEX not in {ix["name"] for ix in sa.inspect(bind).get_indexes(_RFI_TABLE)}:
            op.create_index(_RFI_INDEX, _RFI_TABLE, ["project_id", "request_type"])
    if _TYPE_TABLE not in tables:
        op.create_table(
            _TYPE_TABLE,
            sa.Column("id", GUID(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column(
                "project_id",
                GUID(),
                sa.ForeignKey(
                    "oe_projects_project.id",
                    ondelete="CASCADE",
                    name="fk_oe_rfi_request_type_project_id_oe_projects_project",
                ),
                nullable=False,
            ),
            sa.Column("code", sa.String(length=32), nullable=False),
            sa.Column("name_i18n", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("description_i18n", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("number_prefix", sa.String(length=10), nullable=False),
            sa.Column("number_digits", sa.Integer(), nullable=False, server_default="4"),
            sa.Column("default_response_days", sa.Integer(), nullable=True),
            sa.Column("required_fields", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("default_route_id", GUID(), nullable=True),
            sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("preset_code", sa.String(length=64), nullable=True),
            sa.PrimaryKeyConstraint("id", name="pk_oe_rfi_request_type"),
            sa.UniqueConstraint("project_id", "code", name="uq_rfi_request_type_project_code"),
            sa.UniqueConstraint("project_id", "number_prefix", name="uq_rfi_request_type_project_prefix"),
        )
    if _TYPE_INDEX not in {ix["name"] for ix in sa.inspect(bind).get_indexes(_TYPE_TABLE)}:
        op.create_index(_TYPE_INDEX, _TYPE_TABLE, ["project_id"])


def downgrade() -> None:
    """Drop the catalogue table, then the type column and its index."""
    bind = op.get_bind()
    tables = sa.inspect(bind).get_table_names()
    if _TYPE_TABLE in tables:
        op.drop_table(_TYPE_TABLE)
    if _RFI_TABLE in tables:
        if _RFI_INDEX in {ix["name"] for ix in sa.inspect(bind).get_indexes(_RFI_TABLE)}:
            op.drop_index(_RFI_INDEX, table_name=_RFI_TABLE)
        if "request_type" in {c["name"] for c in sa.inspect(bind).get_columns(_RFI_TABLE)}:
            with op.batch_alter_table(_RFI_TABLE) as batch:
                batch.drop_column("request_type")
