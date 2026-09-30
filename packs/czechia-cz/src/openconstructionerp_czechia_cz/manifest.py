"""Build the ``PartnerPackManifest`` instance for the czechia-cz pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="czechia-cz",
    partner_name="Czech Republic Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for the Czech construction market: CSN standards, "
        "CZK currency with 21% DPH, TSKP classification for building "
        "works, Czech rozpocet (budget) estimating practice."
    ),
    default_locale="cs",
    additional_locales={},
    cwicr_regions=["cwicr-cs-prague"],
    default_currency="CZK",
    default_tax_template="cz_dph_21",
    default_methodology="czechia",
    validation_rule_packs=[],
    validation_rule_sets=[
        "din276",
    ],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["office-prague", "residential-brno"],
    branding=PartnerBranding(
        primary_color="#11457E",  # blue of the Czech flag
        accent_color="#D7141A",  # red of the Czech flag
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path=None,
    metadata={
        "country": "CZ",
        "country_name_en": "Czech Republic",
        "country_name_cs": "Ceska republika",
        "classification_standard": "din276",
        "measurement_system": "metric",
        "regulator_refs": [
            "CSN 73 standards (Ceske technicke normy, construction)",
            "TSKP (Tridnik stavebnich konstrukci a praci, classification of works)",
            "Zakon o zadavani verejnych zakazek 134/2016 Sb. (Public Procurement Act)",
            "Stavebni zakon 283/2021 Sb. (Building Act)",
            "Vyhlaska 169/2016 Sb. (Decree on public works contracts pricing)",
            "CSN EN Eurocodes (Czech adoption of European structural standards)",
        ],
        "vat_standard_rate": 21,
        "vat_reduced_rate": 12,
        "support_email": "info@datadrivenconstruction.io",
    },
)
