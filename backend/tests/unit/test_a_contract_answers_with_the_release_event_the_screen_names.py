# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""A contract answers with a release event the screen has a name for.

Contracts written before the vocabulary was unified store an alias such as
``practical_completion``, and the contract panel printed it raw because the
screen names only the three canonical events. Every response field typed
``ReleaseEvent`` now answers with the canonical name.
"""

from __future__ import annotations

import pytest
from pydantic import TypeAdapter

from app.modules.contracts.schemas import ReleaseEvent

_ADAPTER = TypeAdapter(ReleaseEvent)


@pytest.mark.parametrize(
    ("stored", "shown"),
    [
        ("practical_completion", "substantial_completion"),
        ("substantial_completion", "substantial_completion"),
        ("final_completion", "final_completion"),
        ("defects_period_end", "defects_period_end"),
    ],
)
def test_a_stored_alias_is_answered_by_its_canonical_name(stored: str, shown: str) -> None:
    assert _ADAPTER.validate_python(stored) == shown
