# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""meetings - recordings with transcripts and AI proposals, and the project meeting glossary.

Additive only:

* new table ``oe_meetings_recording``: a meeting's audio (short-lived, with consent and
  retention stamps), its transcript, editable speaker labels and the proposals a person reviews;
* new table ``oe_meetings_glossary_term``: names, companies, abbreviations and terms passed to
  transcription as hints and to the minutes AI as correct spellings.

Every step is inspector-guarded, so a database whose tables ``create_all`` already built
reaches this revision and does nothing.

Revision ID: v201_meetings_recording_glossary
Revises: v200_supplier_pricelists_discounts
Create Date: 2026-10-25
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.database import GUID

revision: str = "v201_meetings_recording_glossary"
down_revision: str | Sequence[str] | None = "v200_supplier_pricelists_discounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RECORDING = "oe_meetings_recording"
_GLOSSARY = "oe_meetings_glossary_term"


def _stamps() -> list[sa.Column]:
    return [
        sa.Column("id", GUID(), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    ]


def upgrade() -> None:
    """Create both tables when missing."""
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "oe_meetings_meeting" not in tables:
        return

    if _RECORDING not in tables:
        op.create_table(
            _RECORDING,
            *_stamps(),
            sa.Column(
                "project_id", GUID(), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column(
                "meeting_id",
                GUID(),
                sa.ForeignKey(
                    "oe_meetings_meeting.id", name="fk_oe_meetings_recording_meeting_id_meeting", ondelete="CASCADE"
                ),
                nullable=False,
            ),
            sa.Column("source", sa.String(20), nullable=False, server_default="upload"),
            sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
            sa.Column("audio_storage_key", sa.String(500), nullable=False, server_default=""),
            sa.Column("audio_filename", sa.String(255), nullable=True),
            sa.Column("audio_size_bytes", sa.Integer(), nullable=True),
            sa.Column("duration_seconds", sa.Integer(), nullable=True),
            sa.Column("audio_expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("audio_deleted_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("delete_audio_after_transcription", sa.Boolean(), nullable=False, server_default="0"),
            sa.Column("consent_confirmed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("consent_confirmed_by", sa.String(36), nullable=True),
            sa.Column("language", sa.String(10), nullable=True),
            sa.Column("transcript", sa.Text(), nullable=False, server_default=""),
            sa.Column("segments", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("speakers", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("provider", sa.String(50), nullable=True),
            sa.Column("transcription_error", sa.String(300), nullable=True),
            sa.Column("proposals", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.Column("metadata", sa.JSON(), nullable=False, server_default="{}"),
        )
        op.create_index("ix_oe_meetings_recording_project_id", _RECORDING, ["project_id"])
        op.create_index("ix_oe_meetings_recording_meeting_id", _RECORDING, ["meeting_id"])
        op.create_index("ix_oe_meetings_recording_audio_expiry", _RECORDING, ["audio_expires_at"])

    if _GLOSSARY not in tables:
        op.create_table(
            _GLOSSARY,
            *_stamps(),
            sa.Column(
                "project_id", GUID(), sa.ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
            ),
            sa.Column("term", sa.String(200), nullable=False),
            sa.Column("term_key", sa.String(200), nullable=False),
            sa.Column("kind", sa.String(20), nullable=False, server_default="term"),
            sa.Column("expansion", sa.String(500), nullable=True),
            sa.Column("aliases", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
            sa.Column("contact_id", sa.String(36), nullable=True),
            sa.Column("created_by", sa.String(36), nullable=True),
            sa.UniqueConstraint("project_id", "term_key", name="uq_oe_meetings_glossary_term_project_key"),
        )
        op.create_index("ix_oe_meetings_glossary_term_project_id", _GLOSSARY, ["project_id"])


def downgrade() -> None:
    """Drop both tables when present."""
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (_GLOSSARY, _RECORDING):
        if table in tables:
            op.drop_table(table)
