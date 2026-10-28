"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠The catalogue must name a currency when the caller cannot.

The BOQ editor saves a resource into the user's own catalogue. It used to
rebuild the currency code from the display symbol, which recognised three
symbols and answered EUR for the rest, so a project in CLP, BRL, PLN or INR
wrote its catalogue rows in euros. It now sends the project's own ISO code, and
where the project never set one it omits the field entirely rather than sending
a blank string.

Omitting is only correct because this schema carries a default. Nothing further
down the path fills a currency in: ``create_resource`` passes ``data.currency``
straight to the column, and the column's own default applies only to an unset
attribute, not to an empty string. So an empty string would validate, store, and
leave a catalogue row that names no currency at all.

These tests pin the two halves of that: the default exists and is a usable code,
and a blank string is not equivalent to omitting the field.
"""

from decimal import Decimal

import pytest

from app.modules.catalog.schemas import CatalogResourceCreate

# The shape the BOQ editor actually posts: one rate, sent as all three prices,
# which is a meaningful band that _check_price_band accepts because base sits on
# it. Written out rather than left on the 0/0 "no band" sentinel so a change to
# that validator shows up here as the band failing, not as the currency.
_REQUIRED = {
    "resource_code": "MY-MAT-TEST",
    "name": "Hormigón H-25",
    "resource_type": "material",
    "category": "Material",
    "unit": "m3",
    "base_price": Decimal("82000"),
    "min_price": Decimal("82000"),
    "max_price": Decimal("82000"),
}


def test_an_omitted_currency_becomes_a_usable_code() -> None:
    """A payload with no currency key still names one."""
    created = CatalogResourceCreate(**_REQUIRED)

    assert created.currency, "the frontend omits the field and relies on this default"
    assert len(created.currency) == 3, f"expected an ISO 4217 code, got {created.currency!r}"
    assert created.currency.isupper()


def test_a_blank_currency_is_not_the_same_as_an_omitted_one() -> None:
    """An empty string is carried through, which is why the caller must omit.

    This pins today's behaviour, not a guarantee worth keeping. If someone adds
    ``min_length=1`` to the field, this test goes red on an improvement: the
    caller omits the field and stays correct either way. Delete it then, rather
    than relaxing the schema to keep it green.
    """
    created = CatalogResourceCreate(**_REQUIRED, currency="")

    assert created.currency == ""


@pytest.mark.parametrize("code", ["CLP", "BRL", "PLN", "INR", "JPY"])
def test_a_currency_the_symbol_map_never_knew_survives(code: str) -> None:
    """The codes the old symbol reconstruction could not express."""
    created = CatalogResourceCreate(**_REQUIRED, currency=code)

    assert created.currency == code
