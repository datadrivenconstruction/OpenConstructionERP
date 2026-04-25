"""v232 — merge money/CO chain with the contact-tenant main chain.

Origin/main accumulated two parallel migration heads:

* ``7f3ab0f2d4e1`` (phase2e_money_numeric) — terminus of the change-order
  / money-numeric chain that branched from
  ``fee2e323c50c_merge_bim_req_with_dwg_annotations`` via
  ``24f9595e16d0`` → ``85f7cfa6eecf`` → ``7f3ab0f2d4e1``.
* ``v231_contact_tenant_id`` — terminus of the asset-register / reporting /
  multi-tenant contacts chain that came through ``v230_*``.

A fresh clone runs ``alembic upgrade head`` and aborts with
``Multiple head revisions are present``.  External users reported the
compile/setup failure that maps to this exact symptom.

This empty merge migration unifies the two heads into a single tip so
``alembic upgrade head`` succeeds again on a fresh database.  No schema
changes — both branches' tables are independent.
"""
from __future__ import annotations

from typing import Sequence, Union

# revision identifiers, used by Alembic.
revision: str = "v232_merge_heads"
down_revision: Union[str, Sequence[str], None] = (
    "7f3ab0f2d4e1",
    "v231_contact_tenant_id",
)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """No-op — the two parent branches don't conflict."""


def downgrade() -> None:
    """No-op — splitting a merge back into two heads is intentional."""
