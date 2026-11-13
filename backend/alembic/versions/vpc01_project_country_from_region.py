# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""backfill project country from region

Projects created before the country was derived from the region carry an empty
country and so miss the national VAT default. Fills only rows whose country is
NULL or empty, from the region label, with the same helper the create path uses.
Idempotent.

Revision ID: vpc01_project_country_from_region
Revises: vlt01_letter_template_overrides
Create Date: 2026-11-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "vpc01_project_country_from_region"
down_revision: str | Sequence[str] | None = "vlt01_letter_template_overrides"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "oe_projects_project"

# boot-repair: registry=project_country_from_region


def upgrade() -> None:
    from app.modules.projects.service import country_from_region

    bind = op.get_bind()
    if _T not in set(sa.inspect(bind).get_table_names()):
        return
    rows = bind.execute(
        sa.text(f"SELECT id, region FROM {_T} WHERE (country_code IS NULL OR country_code = '') AND region <> ''")
    ).all()
    for project_id, region in rows:
        country = country_from_region(region)
        if country:
            bind.execute(
                sa.text(
                    f"UPDATE {_T} SET country_code = :c WHERE id = :i AND (country_code IS NULL OR country_code = '')"
                ),
                {"c": country, "i": project_id},
            )


def downgrade() -> None:
    """Data backfill; the previous values are not recoverable and not needed."""
