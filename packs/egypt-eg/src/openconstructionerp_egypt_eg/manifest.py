"""Build the ``PartnerPackManifest`` instance for the egypt-eg pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="egypt-eg",
    partner_name="Egypt Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for contractors, consultants and owners in Egypt: "
        "MasterFormat classification, EGP currency, the Egyptian national "
        "estimating method, FIDIC-based private contracts and the Public "
        "Contracts Law 182/2018 limits for public works, Egyptian Tax "
        "Authority e-invoicing, and a Sunday to Thursday work week. Value "
        "added tax on contracting works follows the date of the document "
        "(Law 157/2025); the platform resolves it from the project country, "
        "the pack does not set it. English interface, Arabic available."
    ),
    default_locale="en-GB",
    additional_locales={},
    cwicr_regions=[],  # EG_CAIRO_ar is in the base registry but no file is published to load yet
    default_currency="EGP",
    default_tax_template=None,
    default_methodology="egypt",
    validation_rule_packs=[
        "public_contracts_law_182",
        "vat_construction_law_157",
        "eta_einvoicing",
    ],
    validation_rule_sets=[
        "masterformat",
        "boq_quality",
    ],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    demo_template_ids=["residential-cairo"],
    branding=PartnerBranding(
        primary_color="#C09300",  # gold of the national coat of arms
        accent_color="#CE1126",  # red of the flag
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "EG",
        "country_name_en": "Egypt",
        "country_name_ar": "مصر",
        "classification_standard": "masterformat",
        "measurement_system": "metric",
        "regulator_refs": [
            "Public Contracts Law No. 182 of 2018 and Executive Regulations (Decree 692/2019)",
            "Value Added Tax Law No. 157 of 2025 (construction services, Decrees 417 and 418 of 2025)",
            "Egyptian Tax Authority e-invoicing (SDK, invoice v1.0)",
            "Labour Law No. 14 of 2025",
            "Social Insurance Law No. 148 of 2019",
            "FIDIC Red Book 2017 (private and donor-funded works)",
            "Egyptian Federation for Construction and Building Contractors (contractor classification)",
        ],
        "vat_note": (
            "Standard rate 14 percent. Contracting works carried 5 percent without input credit until "
            "2025-07-17 and 14 percent from 2025-07-18. Resolved by document date in core."
        ),
        "work_week": "Sunday to Thursday (Labour Law 14/2025 roster, from 2025-09-01)",
        "cwicr_regions_planned": ["EG_CAIRO_ar"],
        "review_status": (
            "Provisional. Every figure cites its source in the platform data it comes from and was read "
            "on 2026-10-19. The pack has not yet been reviewed by an Egyptian quantity surveyor or tax "
            "adviser; demo rates are illustrative and not a price list."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
