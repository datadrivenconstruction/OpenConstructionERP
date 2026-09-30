"""Build the ``PartnerPackManifest`` instance for the ireland-ie pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="ireland-ie",
    partner_name="Ireland Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for the Irish construction market: ARM/NRM "
        "measurement, EUR currency with 13.5% VAT on construction "
        "services, SCSI quantity surveying practice, RIAI contract "
        "forms, BCAR building control compliance. English interface."
    ),
    default_locale="en-IE",
    additional_locales={},
    cwicr_regions=[],
    default_currency="EUR",
    default_tax_template="ie_vat_13_5",
    default_methodology="ireland",
    validation_rule_packs=[],
    validation_rule_sets=[
        "nrm",
    ],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["office-dublin", "residential-cork"],
    branding=PartnerBranding(
        primary_color="#169B62",  # green of the Irish tricolour
        accent_color="#FF883E",  # orange of the Irish tricolour
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path=None,
    metadata={
        "country": "IE",
        "country_name_en": "Ireland",
        "country_name_ga": "Eire",
        "classification_standard": "nrm",
        "measurement_system": "metric",
        "regulator_refs": [
            "ARM4 (Agreed Rules of Measurement, 4th edition, SCSI/CIF)",
            "NRM 1/2 (RICS New Rules of Measurement, widely used alongside ARM)",
            "Building Control (Amendment) Regulations 2014 (SI No. 9 of 2014, BCAR)",
            "TGD Parts A-M (Technical Guidance Documents, Building Regulations)",
            "RIAI Standard Form of Building Contract (Yellow/Blue)",
            "Public Works Contracts (PWC, Government Contracts Committee)",
            "SCSI (Society of Chartered Surveyors Ireland) practice standards",
        ],
        "vat_construction_rate": 13.5,
        "vat_standard_rate": 23,
        "support_email": "info@datadrivenconstruction.io",
    },
)
