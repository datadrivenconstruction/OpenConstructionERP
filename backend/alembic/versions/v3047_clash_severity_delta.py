# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Clash — severity / signature / comments / due_date triage delta.

Additive, all backward-compatible columns on ``oe_clash_result`` so a
clash can be triaged like a BIM-coordination issue and so
triage persists across re-runs (carry-forward keyed on ``signature``):

* ``severity``  — NOT NULL String(16) default ``'medium'``. Geometry-
                   derived urgency: ``critical | high | medium | low``.
                   The ``medium`` default keeps every legacy row safe.
* ``signature`` — NOT NULL String(16) default ``''``. Run-independent
                  identity of the clashing element pair
                  (``sha1(min|max|clash_type)[:16]``); the engine
                  backfills it on every fresh result. A non-unique
                  ``(run_id, signature)`` index powers the compare /
                  carry-forward lookups.
* ``due_date``  — nullable String(20). ISO-8601 ``YYYY-MM-DD`` deadline
                  (matches this codebase's nullable-date convention,
                  e.g. ``finance.Invoice.due_date``). NULL on legacy rows.
* ``comments``  — NOT NULL JSON default ``[]``. Threaded triage notes.

Idempotent: inspector-guarded so re-running after SQLite's
``Base.metadata.create_all`` / ``sqlite_auto_migrate`` (dev) is a no-op;
Postgres prod gets the DDL.

Revision ID: v3047_clash_severity_delta
Revises: v3046_clash_run_config
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3047_clash_severity_delta"
down_revision: Union[str, Sequence[str], None] = "v3046_clash_run_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RESULT = "oe_clash_result"
_SIG_INDEX = "ix_clash_result_run_sig"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _RESULT):
        return
    cols = {c["name"] for c in inspector.get_columns(_RESULT)}
    if "severity" not in cols:
        op.add_column(
            _RESULT,
            sa.Column(
                "severity",
                sa.String(16),
                nullable=False,
                server_default="medium",
            ),
        )
    if "signature" not in cols:
        op.add_column(
            _RESULT,
            sa.Column(
                "signature",
                sa.String(16),
                nullable=False,
                server_default="",
            ),
        )
    if "due_date" not in cols:
        op.add_column(_RESULT, sa.Column("due_date", sa.String(20), nullable=True))
    if "comments" not in cols:
        op.add_column(
            _RESULT,
            sa.Column(
                "comments",
                sa.JSON(),
                nullable=False,
                server_default="[]",
            ),
        )

    existing_idx = {ix["name"] for ix in inspector.get_indexes(_RESULT)}
    if _SIG_INDEX not in existing_idx:
        op.create_index(_SIG_INDEX, _RESULT, ["run_id", "signature"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _RESULT):
        return
    existing_idx = {ix["name"] for ix in inspector.get_indexes(_RESULT)}
    if _SIG_INDEX in existing_idx:
        op.drop_index(_SIG_INDEX, table_name=_RESULT)
    cols = {c["name"] for c in inspector.get_columns(_RESULT)}
    if "comments" in cols:
        op.drop_column(_RESULT, "comments")
    if "due_date" in cols:
        op.drop_column(_RESULT, "due_date")
    if "signature" in cols:
        op.drop_column(_RESULT, "signature")
    if "severity" in cols:
        op.drop_column(_RESULT, "severity")
