"""Build the ``PartnerPackManifest`` instance for the nigeria-ng pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="nigeria-ng",
    partner_name="Nigeria Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for the Nigerian construction market: BESMM "
        "measurement, NGN currency with 7.5% VAT, NBS standards, "
        "NIQS quantity surveying practice. English interface."
    ),
    default_locale="en-NG",
    additional_locales={},
    cwicr_regions=["cwicr-eng-lagos"],
    default_currency="NGN",
    default_tax_template="ng_vat_7_5",
    default_methodology="nigeria",
    validation_rule_packs=[],
    validation_rule_sets=[
        "nrm",
    ],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["commercial-lagos", "residential-abuja"],
    branding=PartnerBranding(
        primary_color="#008751",  # green of the Nigerian flag
        accent_color="#FFFFFF",  # white of the Nigerian flag
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path=None,
    metadata={
        "country": "NG",
        "country_name_en": "Nigeria",
        "classification_standard": "nrm",
        "measurement_system": "metric",
        "regulator_refs": [
            "BESMM3 (Building and Engineering Standard Method of Measurement, 3rd edition)",
            "NBS (Nigerian Building Standards)",
            "National Building Code of Nigeria 2006",
            "Public Procurement Act 2007 (Bureau of Public Procurement)",
            "NIQS (Nigerian Institute of Quantity Surveyors) practice standards",
            "COREN (Council for the Regulation of Engineering in Nigeria)",
            "ARCON (Architects Registration Council of Nigeria)",
        ],
        "vat_standard_rate": 7.5,
        "support_email": "info@datadrivenconstruction.io",
    },
)
