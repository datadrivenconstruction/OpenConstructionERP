"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠A stock movement that has no unit cost must still serialize.

``StockMovement.unit_cost`` is nullable on purpose: a movement out of a balance
whose average is not knowable has no unit cost to record, and zero would read as
"issued for nothing". The response schema declared it required, so the three
routes that return a movement raised a ``ValidationError`` instead of an answer.
The database write had already succeeded by then, so the operator saw a 500 over
a movement that was in fact recorded.

The second test pins the currency. ``StockMovement`` carries the ISO code the
unit cost is denominated in and the service writes it on every path, but the
response dropped the field, so the number reached the caller with nothing saying
what it was denominated in. The sibling ``StockBalanceResponse`` carries both.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.modules.supplier_catalogs.schemas import StockBalanceResponse, StockMovementResponse


class _Movement:
    """The attribute surface ``model_validate`` reads, with no unit cost."""

    def __init__(self, *, unit_cost: Decimal | None, currency: str | None) -> None:
        self.id = uuid.uuid4()
        self.warehouse_id = uuid.uuid4()
        self.catalog_item_id = uuid.uuid4()
        self.movement_type = "out"
        self.quantity = Decimal("1")
        self.unit_cost = unit_cost
        self.currency = currency
        self.reference_type = None
        self.reference_id = None
        self.batch_lot = None
        self.project_id = None
        self.performed_by = None
        self.performed_at = None
        self.notes = None


def test_a_movement_with_no_unit_cost_serializes_instead_of_raising() -> None:
    """The nullable column must not be a required field."""
    out = StockMovementResponse.model_validate(_Movement(unit_cost=None, currency=None))

    assert out.unit_cost is None
    # None has to mean "not knowable", never zero: a movement issued for
    # nothing is a different statement from a movement whose cost is unknown.
    assert out.unit_cost != Decimal("0")


def test_a_movement_that_has_a_unit_cost_still_carries_it() -> None:
    """The negative control: widening the field must not drop a real value."""
    out = StockMovementResponse.model_validate(_Movement(unit_cost=Decimal("12.5000"), currency="EUR"))

    assert out.unit_cost == Decimal("12.5000")


def test_a_movement_reports_the_currency_its_unit_cost_is_in() -> None:
    """An amount that reaches the caller without its ISO code is not an amount."""
    out = StockMovementResponse.model_validate(_Movement(unit_cost=Decimal("12.5000"), currency="EUR"))

    assert out.currency == "EUR"


def test_the_movement_and_the_balance_agree_on_how_they_answer() -> None:
    """Both sides of the same widening should describe money the same way.

    The balance was updated when the columns were widened and the movement was
    not, which is the whole defect. Comparing the two shapes is what would have
    caught it, so the comparison is what gets pinned.
    """
    for name in ("unit_cost", "currency"):
        field = StockMovementResponse.model_fields[name]
        assert not field.is_required(), f"StockMovementResponse.{name} must not be required"

    assert not StockBalanceResponse.model_fields["unit_cost_avg"].is_required()
    assert not StockBalanceResponse.model_fields["currency"].is_required()
