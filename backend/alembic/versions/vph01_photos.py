# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""photos: one photo archive over the documents gallery

Extends ``oe_documents_photo`` so diary, punch, field report and progress photos
get an index row that points at their existing file (source module and id, hash,
size, GPS accuracy, thumbnail state, location, zone, archive flag). Creates the
album, album item, link, AI suggestion and before/after compare tables.

Revision ID: vph01_photos
Revises: v3354_owner_schedule
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vph01_photos"
down_revision: str | Sequence[str] | None = "v3354_owner_schedule"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PHOTO = "oe_documents_photo"
_ALBUM = "oe_photos_album"
_ITEM = "oe_photos_album_item"
_LINK = "oe_photos_link"
_SUGG = "oe_photos_ai_suggestion"
_CMP = "oe_photos_compare"

_PHOTO_COLUMNS: tuple[tuple[str, sa.types.TypeEngine, dict], ...] = (
    ("source_module", sa.String(32), {"nullable": False, "server_default": "documents"}),
    ("source_id", sa.String(64), {"nullable": True}),
    ("sha256", sa.String(64), {"nullable": True}),
    ("width", sa.Integer(), {"nullable": True}),
    ("height", sa.Integer(), {"nullable": True}),
    ("gps_accuracy_m", sa.Float(), {"nullable": True}),
    ("thumb_status", sa.String(16), {"nullable": False, "server_default": "pending"}),
    ("location_id", sa.String(36), {"nullable": True}),
    ("zone", sa.String(128), {"nullable": True}),
    ("is_archived", sa.Boolean(), {"nullable": False, "server_default": sa.false()}),
)


def _base() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def _photo_fk(name: str = "photo_id") -> sa.Column:
    return sa.Column(name, sa.String(36), sa.ForeignKey(f"{_PHOTO}.id", ondelete="CASCADE"), nullable=False)


def _project_fk() -> sa.Column:
    return sa.Column(
        "project_id", sa.String(36), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())

    existing = {c["name"] for c in inspector.get_columns(_PHOTO)}
    for name, type_, kwargs in _PHOTO_COLUMNS:
        if name not in existing:
            op.add_column(_PHOTO, sa.Column(name, type_, **kwargs))
    indexes = {i["name"] for i in inspector.get_indexes(_PHOTO)}
    if "ix_oe_documents_photo_project_taken" not in indexes:
        op.create_index("ix_oe_documents_photo_project_taken", _PHOTO, ["project_id", "taken_at"])
    if "ix_oe_documents_photo_project_source" not in indexes:
        op.create_index("ix_oe_documents_photo_project_source", _PHOTO, ["project_id", "source_module", "source_id"])
    uniques = {u["name"] for u in inspector.get_unique_constraints(_PHOTO)}
    if "uq_oe_documents_photo_source_file" not in uniques:
        op.create_unique_constraint(
            "uq_oe_documents_photo_source_file", _PHOTO, ["project_id", "source_module", "source_id", "file_path"]
        )

    if _ALBUM not in tables:
        op.create_table(
            _ALBUM,
            *_base(),
            _project_fk(),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("description", sa.Text(), nullable=True),
            sa.Column(
                "cover_photo_id", sa.String(36), sa.ForeignKey(f"{_PHOTO}.id", ondelete="SET NULL"), nullable=True
            ),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", "name", name="uq_oe_photos_album_project_name"),
        )
        op.create_index(f"ix_{_ALBUM}_project_id", _ALBUM, ["project_id"])
    if _ITEM not in tables:
        op.create_table(
            _ITEM,
            sa.Column("album_id", sa.String(36), sa.ForeignKey(f"{_ALBUM}.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("photo_id", sa.String(36), sa.ForeignKey(f"{_PHOTO}.id", ondelete="CASCADE"), primary_key=True),
            sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index(f"ix_{_ITEM}_photo_id", _ITEM, ["photo_id"])
    if _LINK not in tables:
        op.create_table(
            _LINK,
            *_base(),
            _photo_fk(),
            sa.Column("target_kind", sa.String(32), nullable=False),
            sa.Column("target_id", sa.String(64), nullable=False),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("photo_id", "target_kind", "target_id", name="uq_oe_photos_link_target"),
        )
        op.create_index("ix_oe_photos_link_target", _LINK, ["target_kind", "target_id"])
    if _SUGG not in tables:
        op.create_table(
            _SUGG,
            *_base(),
            _photo_fk(),
            sa.Column("kind", sa.String(16), nullable=False),
            sa.Column("payload", sa.JSON(), nullable=False),
            sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
            sa.Column("provider", sa.String(40), nullable=True),
            sa.Column("model", sa.String(120), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
            sa.Column("reviewed_by", sa.String(36), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_oe_photos_ai_suggestion_photo_kind_status", _SUGG, ["photo_id", "kind", "status"])
    if _CMP not in tables:
        op.create_table(
            _CMP,
            *_base(),
            _project_fk(),
            _photo_fk("before_photo_id"),
            _photo_fk("after_photo_id"),
            sa.Column("title", sa.String(200), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
        )
        op.create_index(f"ix_{_CMP}_project_id", _CMP, ["project_id"])


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    for name in (_CMP, _SUGG, _LINK, _ITEM, _ALBUM):
        if name in tables:
            op.drop_table(name)
    uniques = {u["name"] for u in inspector.get_unique_constraints(_PHOTO)}
    if "uq_oe_documents_photo_source_file" in uniques:
        op.drop_constraint("uq_oe_documents_photo_source_file", _PHOTO, type_="unique")
    indexes = {i["name"] for i in inspector.get_indexes(_PHOTO)}
    for name in ("ix_oe_documents_photo_project_source", "ix_oe_documents_photo_project_taken"):
        if name in indexes:
            op.drop_index(name, table_name=_PHOTO)
    existing = {c["name"] for c in inspector.get_columns(_PHOTO)}
    for name, _type, _kwargs in reversed(_PHOTO_COLUMNS):
        if name in existing:
            op.drop_column(_PHOTO, name)
