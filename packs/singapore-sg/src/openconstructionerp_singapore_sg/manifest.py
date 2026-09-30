"""Build the ``PartnerPackManifest`` instance for the singapore-sg pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="singapore-sg",
    partner_name="Singapore Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for the Singapore construction market: SMM7 "
        "measurement rules, SGD currency with 9% GST, BCA regulatory "
        "framework, CONQUAS quality benchmarks, SIA and PSSCOC contract "
        "forms. English interface."
    ),
    default_locale="en-SG",
    additional_locales={},
    cwicr_regions=[],
    default_currency="SGD",
    default_tax_template="sg_gst_9",
    default_methodology="singapore",
    validation_rule_packs=[],
    validation_rule_sets=[
        "nrm",
    ],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["office-singapore", "residential-singapore"],
    branding=PartnerBranding(
        primary_color="#EF3340",  # red of the national flag
        accent_color="#FFFFFF",  # white of the national flag
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path=None,
    metadata={
        "country": "SG",
        "country_name_en": "Singapore",
        "classification_standard": "nrm",
        "measurement_system": "metric",
        "regulator_refs": [
            "Building and Construction Authority (BCA) Building Control Act",
            "SMM7 (Standard Method of Measurement, 7th edition)",
            "CONQUAS (Construction Quality Assessment System)",
            "SIA Conditions of Building Contract",
            "PSSCOC (Public Sector Standard Conditions of Contract)",
            "SS EN standards (Singapore Standards, Eurocode-aligned)",
            "Code of Practice on Buildability (BCA)",
        ],
        "vat_standard_rate": 9,
        "support_email": "info@datadrivenconstruction.io",
    },
)
