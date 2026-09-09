"""The AI estimator must carry the catalogue's per-unit norm, not substitute 1.0.

The catalogue stores a work item's resource buildup in ``CostItem.components``
and writes each component's per-unit norm as ``quantity``. That is established
by arithmetic rather than by the field's name: ``resource_pricing`` prices an
item as the sum over its components of ``quantity * unit_price`` and stores the
result as the item's UNIT rate, so ``quantity`` is per one unit of the item.

The estimator translates that shape into its own at exactly one boundary,
``_resource_breakdown``. That boundary used to read a key the costs module
never writes, so every component fell through to a default of 1.0, and applying
a position then stored, for every resource, a quantity equal to the position's
own quantity.

The failure was invisible on review. The unit rate is written separately from
the chosen candidate at apply time, so the position's money looked right; only
a later edit that re-derives the rate from the buildup exposed it, by which
point the number could be out by two orders of magnitude.

So the assertions below are deliberately about the RELATIONSHIP between the
norm and the parent quantity, not about a single expected figure. A test that
only checked one arithmetic result would pass again the moment some other
default happened to produce it.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from app.modules.ai_estimator.service import AiEstimatorService, _norm_per_unit


class _FakeItem:
    """A catalogue row carrying exactly the components a test supplies."""

    def __init__(self, components: Any) -> None:
        self.components = components


class _FakeSession:
    """Returns one prepared item for any primary key the service asks for."""

    def __init__(self, item: Any) -> None:
        self._item = item

    async def get(self, _model: Any, _pk: Any) -> Any:
        return self._item


def _breakdown(components: Any) -> list[dict[str, Any]]:
    """Run the real boundary against a stubbed session."""
    service = object.__new__(AiEstimatorService)
    service.session = _FakeSession(_FakeItem(components))  # type: ignore[attr-defined]
    return asyncio.run(AiEstimatorService._resource_breakdown(service, str(uuid.uuid4())))


def test_the_catalogue_norm_is_read_from_the_field_the_catalogue_writes() -> None:
    """``quantity`` is the norm, because that is what prices the item."""
    assert _norm_per_unit({"quantity": 0.85}) == (0.85, True)
    assert _norm_per_unit({"quantity": "2.5"}) == (2.5, True)


def test_a_component_declaring_no_norm_is_marked_rather_than_assumed_silently() -> None:
    """The negative control: 1.0 is allowed, but never allowed to look grounded.

    A plausible default that changes no visible result is precisely how the
    original defect stayed hidden, so the fallback has to announce itself.
    """
    assert _norm_per_unit({}) == (1.0, False)
    assert _norm_per_unit({"quantity": None}) == (1.0, False)
    assert _norm_per_unit({"quantity": 0}) == (1.0, False)
    assert _norm_per_unit({"quantity": "not a number"}) == (1.0, False)


def test_a_group_persisted_under_the_older_spelling_keeps_its_meaning() -> None:
    """Groups written by an earlier revision carry ``factor``; honour it."""
    assert _norm_per_unit({"factor": 0.4}) == (0.4, True)
    # The catalogue's own field wins when a row somehow carries both.
    assert _norm_per_unit({"quantity": 0.85, "factor": 1.0}) == (0.85, True)


def test_the_breakdown_carries_the_norm_instead_of_flattening_it_to_one() -> None:
    rows = _breakdown(
        [
            {"code": "L1", "description": "Bricklayer", "unit": "h", "quantity": 0.85, "unit_rate": "42.00"},
            {"code": "M1", "description": "Brick", "unit": "pcs", "quantity": 58.0, "unit_rate": "0.55"},
        ]
    )
    assert [r["factor"] for r in rows] == [0.85, 58.0]
    assert not any("factor_estimated" in r for r in rows)


def test_an_ungrounded_component_reaches_review_flagged() -> None:
    rows = _breakdown([{"code": "X", "description": "Unknown", "unit": "pcs", "unit_rate": "1.00"}])
    assert rows[0]["factor"] == 1.0
    assert rows[0]["factor_estimated"] is True


@pytest.mark.parametrize("parent_qty", [1.0, 12.0, 100.0, 2400.0])
def test_the_stored_quantity_is_the_norm_whatever_the_parent_quantity(parent_qty: float) -> None:
    """The invariant the original defect violated, stated as a relationship.

    Apply stores each row's ``quantity`` per ONE unit of the position, which is
    the catalogue norm itself, so the stored quantity does not move with the
    parent quantity and differs from it whenever the norm is not 1.0. Under
    the defect the two were always equal, for every resource on every
    position, and that equality is what this asserts against - not one
    expected number, which a different wrong default could reproduce by
    accident. Before 17.1.0 apply stored ``factor * parent_qty`` instead, a
    whole-position total that priced the line correctly until an edit
    re-derived the unit rate from it.
    """
    norm = 0.85
    rows = _breakdown([{"code": "L1", "description": "Bricklayer", "unit": "h", "quantity": norm}])

    stored = AiEstimatorService._per_unit_rows(rows)[0]["quantity"]

    assert stored == pytest.approx(norm)
    assert stored != pytest.approx(parent_qty), "the buildup collapsed onto the position quantity"
    if parent_qty != 1.0:
        assert stored != pytest.approx(norm * parent_qty), "a whole-position total was stored"


def test_a_norm_of_exactly_one_is_the_one_case_the_two_legitimately_coincide() -> None:
    """Guards the guard: the invariant above must not be read as 'never equal'."""
    rows = _breakdown([{"code": "M1", "description": "Panel", "unit": "pcs", "quantity": 1.0}])
    assert rows[0]["factor"] * 40.0 == pytest.approx(40.0)
    assert not any("factor_estimated" in r for r in rows)


def test_a_non_dict_component_is_skipped_rather_than_crashing_the_run() -> None:
    rows = _breakdown([{"code": "L1", "quantity": 2.0}, "not a component", None])
    assert len(rows) == 1
    assert rows[0]["factor"] == 2.0
