"""Build the ``PartnerPackManifest`` instance for the us-florida pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="us-florida",
    partner_name="Florida Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "State depth for Florida on top of the US pack: the contractor as the "
        "ultimate consumer of the materials it installs under a lump sum contract, "
        "the county surtax that stops at the first 5,000 dollars of a single item, "
        "the preemption of local wage terms in public contracts, the 5 percent "
        "public retainage cap, the local government payment clock, and the notice "
        "to owner and claim of lien deadlines."
    ),
    default_locale="en-US",
    # Florida changes the rules, not the words; en-US and the national pack's
    # vocabulary serve it, and es-MX serves Spanish-speaking field crews.
    additional_locales={},
    cwicr_regions=["cwicr-usa-usd"],
    default_currency="USD",
    default_tax_template=None,
    default_methodology="united_states",
    validation_rule_packs=["fl_statutory_checks"],
    validation_rule_sets=["masterformat"],
    # A general contractor's working set on a US state job: estimate and bill,
    # programme, buy and subcontract, bill and hold retainage, certify payroll,
    # track lien and payment deadlines, and run the field record.
    default_modules=[
        "oe_costs",
        "oe_boq",
        "oe_schedule",
        "oe_procurement",
        "oe_subcontractors",
        "oe_contracts",
        "oe_payment_clock",
        "oe_certified_payroll",
        "oe_deadlines",
        "oe_statutory",
        "oe_documents",
        "oe_rfi",
        "oe_changeorders",
        "oe_daily_diary",
        "oe_safety",
    ],
    hidden_modules=[],
    demo_template_ids=["condo-miami"],
    branding=PartnerBranding(
        primary_color="#0B5394",
        accent_color="#F28C28",
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "US",
        "country_name_en": "United States",
        "subdivision": "US-FL",
        "subdivision_name_en": "Florida",
        "region_focus": "Florida (US-FL)",
        "backend_module": "oe_us_fl_pack",
        "parent_pack": "us-costdata",
        "regulator_refs": [
            "Florida Statutes Chapter 212 (sales and use tax), § 212.054 (discretionary surtax)",
            "Florida Administrative Code Rule 12A-1.051 (real property contractors)",
            "Florida Statutes § 218.077 (local wage preemption, as amended by ch. 2024-80)",
            "Florida Statutes § 218.735 (Local Government Prompt Payment Act)",
            "Florida Statutes § 255.078 (state public construction retainage)",
            "Florida Statutes § 715.12 (private prompt payment)",
            "Florida Statutes Chapter 713, Part I (Construction Liens)",
            "Florida Statutes Chapter 489, Part I (contractor licensing)",
            "Florida Building Code, 8th Edition (2023)",
        ],
        "state_rule_topics": ["sales_tax", "prevailing_wage", "retainage", "prompt_payment", "lien"],
        "payment_clock_regimes": ["us_fl_public_local_218735"],
        "payroll_export_profiles": ["us_wh347_csv"],
        "state_general_contractor_licence": True,
        "support_email": "info@datadrivenconstruction.io",
    },
)
