# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Every demo that is meant to open with an e-invoice screen carries a usable showcase.

The settings seeder copies the seller out of each demo's showcase invoice, so a
demo without ``einvoice_showcase`` opens on an empty form. Pinned here for the
demos that were missing it: the declared profile is one the engine writes, and
the seller and payment block passes the same validators the settings screen
applies on save.
"""

from __future__ import annotations

import pytest

import app.core.demo_projects as demo_projects
from app.modules.einvoice.profiles import PROFILES
from app.modules.finance.einvoice_settings_models import _PAYMENT_FIELDS, _SELLER_FIELDS
from app.modules.finance.einvoice_settings_schemas import EInvoiceSettingsRead, EInvoiceSettingsUpdate

# demo id -> (profile, seller country)
_DEMOS = {
    "residential-berlin": ("xrechnung", "DE"),
    "school-paris": ("facturx", "FR"),
    "office-london": ("peppol", "GB"),
    "office-toronto": ("ubl", "CA"),
    "office-shanghai": ("ubl", "CN"),
    "warehouse-dubai": ("peppol", "AE"),
    "office-frankfurt": (None, "DE"),
    "full-showcase-riyadh": (None, "SA"),
    "hospital-lima": (None, "PE"),
}


def _settings_payload(showcase: dict) -> dict[str, str]:
    ei = showcase["einvoice"]
    seller = ei["seller"]
    values = {f"seller_{n}": str(seller.get(n) or "") for n in _SELLER_FIELDS}
    values.update({n: str(ei.get(n) or "") for n in _PAYMENT_FIELDS})
    return {k: v for k, v in values.items() if v}


@pytest.mark.parametrize("demo_id", sorted(_DEMOS))
def test_demo_seeds_one_valid_settings_row(demo_id: str) -> None:
    template = demo_projects.DEMO_TEMPLATES[demo_id]
    showcase = template.einvoice_showcase
    assert showcase, f"{demo_id} has no e-invoice showcase, so its settings screen opens empty"
    profile, country = _DEMOS[demo_id]
    if profile:
        assert showcase.get("profile") == profile
        assert profile in PROFILES, "the declared profile is not one the engine writes"

    payload = _settings_payload(showcase)
    assert payload["seller_country_code"] == country
    # The screen's own write validators (country, VAT shape, IBAN, means code, EAS scheme).
    update = EInvoiceSettingsUpdate(**payload)
    view = EInvoiceSettingsRead.from_row(update)
    assert view.missing == [], f"{demo_id}: settings form would still report gaps: {view.missing}"


@pytest.mark.parametrize("demo_id", sorted(d for d, (p, _) in _DEMOS.items() if p))
def test_showcase_invoice_is_complete(demo_id: str) -> None:
    showcase = demo_projects.DEMO_TEMPLATES[demo_id].einvoice_showcase
    assert showcase["invoice"]["invoice_number"]
    lines = showcase["invoice"]["line_items"]
    assert lines
    for line in lines:
        # Whole currency units keep the header (float) and the EN 16931 engine (Decimal) in agreement.
        assert line["amount"].endswith(".00") and line["amount"] == line["unit_rate"]
    assert showcase["buyer_contact"]["legal_name"]
    ei = showcase["einvoice"]
    # Peppol and XRechnung both demand a buyer reference (BT-10).
    assert ei.get("buyer_reference") or ei.get("leitweg_id")
    assert float(ei["vat_rate"]) >= 0
    # A seller VAT id, when present, carries its country prefix (BR-CO-9).
    vat = ei["seller"].get("vat_id")
    assert not vat or vat[:2].isalpha()
