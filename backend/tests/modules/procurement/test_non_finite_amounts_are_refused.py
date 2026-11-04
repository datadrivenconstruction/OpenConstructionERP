"""NaN and Infinity must be refused at the schema, not stored or turned into a 500."""

import pytest
from pydantic import ValidationError

from app.modules.procurement.schemas import GRItemCreate, PORetainageReleaseRequest


@pytest.mark.parametrize("bad", ["NaN", "sNaN", "Infinity", "-Infinity", "-1", "abc"])
def test_retainage_release_refuses_non_finite_or_non_positive(bad):
    with pytest.raises(ValidationError):
        PORetainageReleaseRequest(amount=bad)


def test_retainage_release_accepts_a_plain_amount():
    assert PORetainageReleaseRequest(amount="125.50").amount == "125.50"


@pytest.mark.parametrize("bad", ["NaN", "Infinity"])
def test_receipt_quantity_refuses_non_finite(bad):
    with pytest.raises(ValidationError):
        GRItemCreate(description="Rebar", quantity_ordered="10", quantity_received=bad)
