# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The demo estate must speak the variations module's own status vocabulary.

The demo generator wrote "agreed" and "implemented" on two of every three
variation orders. Both read naturally in English and neither is in
``_VO_STATUS``, the pattern the module validates writes against, so the seeded
rows carried a status the module itself would refuse and could not offer back
in a status dropdown. Nothing caught it because the seeder inserts through the
ORM and never passes the Pydantic layer that owns the vocabulary.

The second test exists so this file cannot pass by being toothless: it feeds the
exact string that was wrong through the same assertion and requires it to be
rejected.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime

import pytest

from app.core.demo_projects import DEMO_TEMPLATES, _generate_module_data
from app.modules.variations.schemas import _VO_STATUS

_ALLOWED = re.compile(_VO_STATUS)


def _generate(demo_id: str) -> list[dict]:
    """Variation-order rows the generator would seed for one demo template."""
    template = DEMO_TEMPLATES[demo_id]
    data = _generate_module_data(
        template,
        project_id=uuid.uuid4(),
        owner_id=uuid.uuid4(),
        demo_id=demo_id,
        base=datetime(2026, 1, 15, tzinfo=UTC),
    )
    return data.get("variations", [])


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_every_generated_variation_order_carries_a_status_the_module_accepts(
    demo_id: str,
) -> None:
    rows = _generate(demo_id)
    assert rows, f"{demo_id} generated no variation orders, the check would be vacuous"

    offenders = [r["status"] for r in rows if not _ALLOWED.match(r["status"])]
    assert not offenders, f"{demo_id} seeds variation orders with statuses outside _VO_STATUS: {sorted(set(offenders))}"


def test_the_check_rejects_the_status_that_was_actually_wrong() -> None:
    """A green run above must mean the data is right, not that nothing is read."""
    for was_written in ("agreed", "implemented"):
        assert not _ALLOWED.match(was_written)


@pytest.mark.parametrize("demo_id", sorted(DEMO_TEMPLATES))
def test_generated_variation_orders_are_priced_in_the_template_currency(
    demo_id: str,
) -> None:
    """Money on a demo row belongs to the project, not to the seeder's default.

    The variations seeder wrote EUR on every row regardless of the project, so a
    Dubai project listed AED and EUR orders side by side with no rate between
    them.
    """
    expected = DEMO_TEMPLATES[demo_id].currency or ""
    wrong = [r["currency"] for r in _generate(demo_id) if r["currency"] != expected]
    assert not wrong, f"{demo_id} expects {expected!r}, got {sorted(set(wrong))}"
