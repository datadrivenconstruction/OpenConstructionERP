# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""assemblies: optional component-level input tax

Adds the tax profile (``tax_code``, ``tax_rate``, ``tax_status``,
``price_includes_tax``, ``input_tax_treatment``) to ``oe_catalog_resource`` and
``oe_assemblies_component``, and the project switch (``component_tax_enabled``,
``component_tax_treatment``) to ``oe_projects_project``.

Every new column on the two cost tables is nullable (NULL = unclassified), and the
project switch defaults to off, so an existing install prices exactly as before.
Each add is guarded by a column check, so it is safe on an install whose tables
came from ``create_all``.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vct01_component_tax"
down_revision: str | Sequence[str] | None = "vsm01_sensor_manual_readings"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_RESOURCE = "oe_catalog_resource"
_COMPONENT = "oe_assemblies_component"
_PROJECT = "oe_projects_project"

_PROFILE = (
    ("tax_code", sa.String(50)),
    ("tax_rate", sa.String(20)),
    ("tax_status", sa.String(20)),
    ("price_includes_tax", sa.Boolean()),
    ("input_tax_treatment", sa.String(20)),
)


def _columns(insp: sa.Inspector, table: str) -> set[str]:
    if not insp.has_table(table):
        return set()
    return {c["name"] for c in insp.get_columns(table)}


def upgrade() -> None:
    insp = sa.inspect(op.get_bind())
    for table in (_RESOURCE, _COMPONENT):
        have = _columns(insp, table)
        if not have:
            continue
        for name, kind in _PROFILE:
            if name not in have:
                op.add_column(table, sa.Column(name, kind, nullable=True))
    have = _columns(insp, _PROJECT)
    if have and "component_tax_enabled" not in have:
        op.add_column(
            _PROJECT,
            sa.Column("component_tax_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if have and "component_tax_treatment" not in have:
        op.add_column(
            _PROJECT,
            sa.Column("component_tax_treatment", sa.String(20), nullable=False, server_default="recoverable"),
        )


def downgrade() -> None:
    insp = sa.inspect(op.get_bind())
    have = _columns(insp, _PROJECT)
    for name in ("component_tax_treatment", "component_tax_enabled"):
        if name in have:
            op.drop_column(_PROJECT, name)
    for table in (_COMPONENT, _RESOURCE):
        have = _columns(insp, table)
        for name, _ in reversed(_PROFILE):
            if name in have:
                op.drop_column(table, name)
