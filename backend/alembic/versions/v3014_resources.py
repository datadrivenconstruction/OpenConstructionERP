# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""v3014 — resources module (Module 3: Graphical Resource Planning).

Adds the eight resources tables (resource / skill / resource_skill /
certification / availability_window / assignment / resource_request /
resource_link) backing the Graphical Resource Planning module.

Idempotent — re-applying on a DB where ``Base.metadata.create_all`` has
already created the tables is a no-op. Index creation is wrapped in
``try/except OperationalError`` to tolerate metadata having pre-created
single-column indexes via ``index=True`` on the model.

Revision ID: v3014_resources
Revises: v3013_portal
Create Date: 2026-05-12
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v3014_resources"
down_revision: Union[str, Sequence[str], None] = "v3013_portal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# (table_name, [(index_name, [cols], unique)])
_TABLE_INDEXES: dict[str, list[tuple[str, list[str], bool]]] = {
    "oe_resources_resource": [
        ("ix_oe_resources_resource_code", ["code"], True),
        ("ix_oe_resources_resource_resource_type", ["resource_type"], False),
        ("ix_oe_resources_resource_home_project_id", ["home_project_id"], False),
        ("ix_oe_resources_resource_status", ["status"], False),
    ],
    "oe_resources_skill": [
        ("ix_oe_resources_skill_code", ["code"], True),
        ("ix_oe_resources_skill_category", ["category"], False),
    ],
    "oe_resources_resource_skill": [
        (
            "ix_oe_resources_resource_skill_resource_skill",
            ["resource_id", "skill_id"],
            False,
        ),
    ],
    "oe_resources_certification": [
        ("ix_oe_resources_certification_resource_id", ["resource_id"], False),
        ("ix_oe_resources_certification_cert_type", ["cert_type"], False),
        ("ix_oe_resources_certification_valid_until", ["valid_until"], False),
        ("ix_oe_resources_certification_status", ["status"], False),
    ],
    "oe_resources_availability_window": [
        (
            "ix_oe_resources_availability_window_resource_start",
            ["resource_id", "start_at"],
            False,
        ),
    ],
    "oe_resources_assignment": [
        (
            "ix_oe_resources_assignment_resource_start",
            ["resource_id", "start_at"],
            False,
        ),
        (
            "ix_oe_resources_assignment_project_start",
            ["project_id", "start_at"],
            False,
        ),
        ("ix_oe_resources_assignment_task_id", ["task_id"], False),
        ("ix_oe_resources_assignment_work_order_id", ["work_order_id"], False),
        ("ix_oe_resources_assignment_status", ["status"], False),
    ],
    "oe_resources_resource_request": [
        ("ix_oe_resources_resource_request_project_id", ["project_id"], False),
        ("ix_oe_resources_resource_request_priority", ["priority"], False),
        ("ix_oe_resources_resource_request_status", ["status"], False),
    ],
    "oe_resources_resource_link": [
        (
            "ix_oe_resources_resource_link_primary_secondary",
            ["primary_resource_id", "secondary_resource_id"],
            False,
        ),
    ],
}


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def _has_index(inspector: sa.engine.reflection.Inspector, table: str, index: str) -> bool:
    if not _has_table(inspector, table):
        return False
    return any(ix["name"] == index for ix in inspector.get_indexes(table))


def _create_index_idempotent(name: str, table: str, cols: list[str], *, unique: bool = False) -> None:
    """Create an index, swallowing OperationalError for already-existing entries.

    ``Base.metadata.create_all`` (run at app startup for SQLite) may have
    already created indexes from column-level ``index=True``. Wrap in
    try/except so the migration is tolerant.
    """
    try:
        op.create_index(name, table, cols, unique=unique)
    except sa.exc.OperationalError:
        # Already created by metadata.create_all
        pass


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    is_sqlite = bind.dialect.name == "sqlite"
    guid_type = sa.String(36) if is_sqlite else sa.dialects.postgresql.UUID(as_uuid=True)

    # ── oe_resources_resource ────────────────────────────────────────
    if not _has_table(inspector, "oe_resources_resource"):
        op.create_table(
            "oe_resources_resource",
            sa.Column("id", guid_type, primary_key=True),
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
            sa.Column("code", sa.String(50), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column(
                "resource_type",
                sa.String(32),
                nullable=False,
                server_default="person",
            ),
            sa.Column(
                "home_project_id",
                guid_type,
                sa.ForeignKey("oe_projects_project.id", ondelete="SET NULL"),
                nullable=True,
            ),
            # FK to oe_contacts_contact is declared ONLY here, not in the ORM,
            # because test fixtures don't load the contacts module.
            sa.Column("contact_id", guid_type, nullable=True),
            sa.Column(
                "default_cost_rate",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("status", sa.String(32), nullable=False, server_default="active"),
            sa.Column("avatar_url", sa.String(1024), nullable=True),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )
        # Add FK to oe_contacts_contact only if that table exists at upgrade
        # time. The migration is robust to either ordering of agent merges.
        inspector_post = sa.inspect(bind)
        if _has_table(inspector_post, "oe_contacts_contact") and not is_sqlite:
            # SQLite doesn't support ALTER TABLE ADD CONSTRAINT; skip on sqlite.
            try:
                op.create_foreign_key(
                    "fk_oe_resources_resource_contact_id_oe_contacts_contact",
                    "oe_resources_resource",
                    "oe_contacts_contact",
                    ["contact_id"],
                    ["id"],
                    ondelete="SET NULL",
                )
            except (sa.exc.OperationalError, sa.exc.ProgrammingError):
                pass

    # ── oe_resources_skill ───────────────────────────────────────────
    if not _has_table(inspector, "oe_resources_skill"):
        op.create_table(
            "oe_resources_skill",
            sa.Column("id", guid_type, primary_key=True),
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
            sa.Column("code", sa.String(64), nullable=False),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("category", sa.String(32), nullable=False, server_default="trade"),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── oe_resources_resource_skill ──────────────────────────────────
    if not _has_table(inspector, "oe_resources_resource_skill"):
        op.create_table(
            "oe_resources_resource_skill",
            sa.Column("id", guid_type, primary_key=True),
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
            sa.Column(
                "resource_id",
                guid_type,
                sa.ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "skill_id",
                guid_type,
                sa.ForeignKey("oe_resources_skill.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("level", sa.String(16), nullable=False, server_default="competent"),
            sa.Column("acquired_at", sa.String(20), nullable=True),
            sa.Column("expires_at", sa.String(20), nullable=True),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── oe_resources_certification ───────────────────────────────────
    if not _has_table(inspector, "oe_resources_certification"):
        op.create_table(
            "oe_resources_certification",
            sa.Column("id", guid_type, primary_key=True),
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
            sa.Column(
                "resource_id",
                guid_type,
                sa.ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("cert_type", sa.String(128), nullable=False),
            sa.Column("cert_number", sa.String(128), nullable=True),
            sa.Column("issued_by", sa.String(255), nullable=True),
            sa.Column("issue_date", sa.String(20), nullable=True),
            sa.Column("valid_until", sa.String(20), nullable=True),
            sa.Column("document_url", sa.String(1024), nullable=True),
            sa.Column("status", sa.String(16), nullable=False, server_default="valid"),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── oe_resources_availability_window ─────────────────────────────
    if not _has_table(inspector, "oe_resources_availability_window"):
        op.create_table(
            "oe_resources_availability_window",
            sa.Column("id", guid_type, primary_key=True),
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
            sa.Column(
                "resource_id",
                guid_type,
                sa.ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "window_type",
                sa.String(16),
                nullable=False,
                server_default="available",
            ),
            sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("recurrence_rule", sa.String(512), nullable=True),
            sa.Column("note", sa.Text(), nullable=False, server_default=""),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── oe_resources_assignment ──────────────────────────────────────
    if not _has_table(inspector, "oe_resources_assignment"):
        op.create_table(
            "oe_resources_assignment",
            sa.Column("id", guid_type, primary_key=True),
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
            sa.Column(
                "resource_id",
                guid_type,
                sa.ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey("oe_projects_project.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "task_id",
                guid_type,
                sa.ForeignKey("oe_tasks_task.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("work_order_id", sa.String(36), nullable=True),
            sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column(
                "allocation_percent",
                sa.Integer(),
                nullable=False,
                server_default="100",
            ),
            sa.Column("status", sa.String(16), nullable=False, server_default="proposed"),
            sa.Column(
                "cost_rate",
                sa.Numeric(18, 4),
                nullable=False,
                server_default="0",
            ),
            sa.Column("currency", sa.String(3), nullable=False, server_default=""),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── oe_resources_resource_request ────────────────────────────────
    if not _has_table(inspector, "oe_resources_resource_request"):
        op.create_table(
            "oe_resources_resource_request",
            sa.Column("id", guid_type, primary_key=True),
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
            sa.Column(
                "project_id",
                guid_type,
                sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("requested_by", sa.String(36), nullable=True),
            sa.Column("title", sa.String(500), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("required_skills", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("priority", sa.String(16), nullable=False, server_default="med"),
            sa.Column("status", sa.String(16), nullable=False, server_default="open"),
            sa.Column(
                "fulfilled_assignment_id",
                guid_type,
                sa.ForeignKey("oe_resources_assignment.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # ── oe_resources_resource_link ──────────────────────────────────
    if not _has_table(inspector, "oe_resources_resource_link"):
        op.create_table(
            "oe_resources_resource_link",
            sa.Column("id", guid_type, primary_key=True),
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
            sa.Column(
                "primary_resource_id",
                guid_type,
                sa.ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "secondary_resource_id",
                guid_type,
                sa.ForeignKey("oe_resources_resource.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("link_type", sa.String(32), nullable=False, server_default="buddy"),
            sa.Column("notes", sa.Text(), nullable=False, server_default=""),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )

    # Indexes (idempotent, OperationalError-tolerant).
    inspector = sa.inspect(bind)  # refresh after CREATE TABLE
    for table, indexes in _TABLE_INDEXES.items():
        if not _has_table(inspector, table):
            continue
        for name, cols, unique in indexes:
            if _has_index(inspector, table, name):
                continue
            _create_index_idempotent(name, table, cols, unique=unique)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    # Drop in reverse FK-dependency order
    drop_order = [
        "oe_resources_resource_link",
        "oe_resources_resource_request",
        "oe_resources_assignment",
        "oe_resources_availability_window",
        "oe_resources_certification",
        "oe_resources_resource_skill",
        "oe_resources_skill",
        "oe_resources_resource",
    ]
    for table in drop_order:
        if not _has_table(inspector, table):
            continue
        for name, _cols, _unique in _TABLE_INDEXES.get(table, []):
            if _has_index(inspector, table, name):
                try:
                    op.drop_index(name, table_name=table)
                except sa.exc.OperationalError:
                    pass
        op.drop_table(table)
