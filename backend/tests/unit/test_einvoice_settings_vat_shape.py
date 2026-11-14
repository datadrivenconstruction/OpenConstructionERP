"""The settings schema accepts a bare national registration when the country is stated."""

import pytest
from pydantic import ValidationError

from app.modules.finance.einvoice_settings_schemas import EInvoiceSettingsUpdate


def test_bare_ksa_vat_number_with_country_is_accepted() -> None:
    row = EInvoiceSettingsUpdate(seller_vat_id="300451299900003", seller_country_code="SA")
    assert row.seller_vat_id == "300451299900003"


def test_prefixed_vat_id_still_accepted() -> None:
    assert EInvoiceSettingsUpdate(seller_vat_id="de123456789").seller_vat_id == "DE123456789"


@pytest.mark.parametrize(
    "kwargs", [{"seller_vat_id": "300451299900003"}, {"seller_vat_id": "12345", "seller_country_code": "SA"}]
)
def test_bare_vat_without_country_or_too_short_is_refused(kwargs: dict) -> None:
    with pytest.raises(ValidationError):
        EInvoiceSettingsUpdate(**kwargs)
