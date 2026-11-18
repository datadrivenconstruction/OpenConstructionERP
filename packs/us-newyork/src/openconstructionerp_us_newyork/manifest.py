"""Build the ``PartnerPackManifest`` instance for the us-newyork pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="us-newyork",
    partner_name="New York Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "State depth for New York on top of the US pack: the line between a "
        "capital improvement and a repair that decides whether the customer is "
        "taxed on the whole bill or the contractor on its materials, the Article 8 "
        "prevailing wage schedules and electronic certified payroll, the private "
        "retainage cap on contracts of 150 thousand dollars or more, the state and "
        "local payment clocks, and the mechanic's lien filing window."
    ),
    default_locale="en-US",
    # New York changes the rules, not the words; en-US and the national pack's
    # vocabulary serve it, and es-MX serves Spanish-speaking field crews.
    additional_locales={},
    cwicr_regions=["cwicr-usa-usd"],
    default_currency="USD",
    default_tax_template=None,
    default_methodology="united_states",
    validation_rule_packs=["ny_statutory_checks"],
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
    demo_template_ids=["residential-bronx"],
    branding=PartnerBranding(
        primary_color="#002D72",
        accent_color="#FF6319",
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "US",
        "country_name_en": "United States",
        "subdivision": "US-NY",
        "subdivision_name_en": "New York",
        "region_focus": "New York (US-NY)",
        "backend_module": "oe_us_ny_pack",
        "parent_pack": "us-costdata",
        "regulator_refs": [
            "New York Tax Law §§ 1101(b)(9), 1105(c) and 1210 (sales and use tax, capital improvements)",
            "Form ST-124 (Certificate of Capital Improvement)",
            "New York Labor Law Article 8, § 220 (prevailing wage on public work)",
            "New York Labor Law § 224-a (covered private projects)",
            "New York General Business Law Article 35-E, §§ 756 to 758 (private prompt payment and retainage)",
            "New York State Finance Law § 139-f and § 179-f (state contracts)",
            "New York General Municipal Law § 106-b (local public payment)",
            "New York Lien Law § 10 (filing of notice of lien)",
            "2022 New York City Building Code",
        ],
        "state_rule_topics": ["sales_tax", "prevailing_wage", "retainage", "prompt_payment", "lien"],
        "payment_clock_regimes": ["us_ny_public_state_179f", "us_ny_public_local_106b", "us_ny_private_756a"],
        "payroll_export_profiles": ["ny_dol_payroll_xml", "us_wh347_csv"],
        "state_general_contractor_licence": False,
        "support_email": "info@datadrivenconstruction.io",
    },
)
