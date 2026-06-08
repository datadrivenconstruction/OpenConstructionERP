# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Clash — explicit run configuration (type / scope / description).

Additive, all backward-compatible columns on ``oe_clash_run`` so a run
is reproducible and identifiable in history (BIM-coordination tool style
run configuration):

* ``description``       — nullable Text. Free-text note (scope / intent /
                          reviewer). NULL on every pre-existing run.
* ``clash_type``        — NOT NULL String(16) default ``'both'``. Which
                          interference an engine pass reports:
                          ``hard`` (interpenetration only),
                          ``clearance`` (proximity only) or ``both`` (the
                          historical behaviour — hard, then clearance for
                          the non-hard pairs). Default ``'both'`` keeps
                          every existing run's semantics identical.
* ``ignore_same_model`` — NOT NULL Boolean default ``False``. Federated
                          noise filter ("ignore clashes within the same
                          file"); no effect on a single-model run.

Idempotent: inspector-guarded so re-running after SQLite's
``Base.metadata.create_all`` / ``sqlite_auto_migrate`` (dev) is a no-op;
Postgres prod gets the DDL.

Revision ID: v3046_clash_run_config
Revises: v3045_webhook_leads
Created: 2026-05-19
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "v3046_clash_run_config"
down_revision: Union[str, Sequence[str], None] = "v3045_webhook_leads"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_RUN = "oe_clash_run"


def _has_table(inspector: sa.engine.reflection.Inspector, name: str) -> bool:
    return name in inspector.get_table_names()


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _RUN):
        return
    cols = {c["name"] for c in inspector.get_columns(_RUN)}
    if "description" not in cols:
        op.add_column(_RUN, sa.Column("description", sa.Text(), nullable=True))
    if "clash_type" not in cols:
        op.add_column(
            _RUN,
            sa.Column(
                "clash_type",
                sa.String(16),
                nullable=False,
                server_default="both",
            ),
        )
    if "ignore_same_model" not in cols:
        op.add_column(
            _RUN,
            sa.Column(
                "ignore_same_model",
                sa.Boolean(),
                nullable=False,
                server_default="0",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _has_table(inspector, _RUN):
        return
    cols = {c["name"] for c in inspector.get_columns(_RUN)}
    if "ignore_same_model" in cols:
        op.drop_column(_RUN, "ignore_same_model")
    if "clash_type" in cols:
        op.drop_column(_RUN, "clash_type")
    if "description" in cols:
        op.drop_column(_RUN, "description")
