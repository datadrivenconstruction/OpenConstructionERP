"""Build the ``PartnerPackManifest`` instance for the us-california pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="us-california",
    partner_name="California Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "State depth for California on top of the US pack: district sales tax "
        "stacked on the statewide base and the split between materials the "
        "contractor consumes and fixtures it sells, the state prevailing wage "
        "regime with its 1,000 dollar threshold and registration duty, the "
        "public and private retention caps including the 2026 private cap, and "
        "the statutory payment and mechanics lien clocks."
    ),
    default_locale="en-US",
    # No locale file of its own. en-US is a core locale and the national pack
    # already carries the US construction vocabulary; a California copy of those
    # hundred keys would only give the tree somewhere to drift. California
    # changes the rules, not the words.
    additional_locales={},
    # There is no California-specific CWICR pack. The national USD pack is the
    # cost region; the city cost index carried by us-costdata localises it, and
    # Los Angeles and San Francisco are both in its pre-offered metro list.
    cwicr_regions=["cwicr-usa-usd"],
    default_currency="USD",
    default_tax_template="us_state_sales_tax",
    default_methodology="united_states",
    validation_rule_packs=[
        "ca_sales_tax_contractors",
        "ca_prevailing_wage_labor_code",
        "ca_retention_caps",
        "ca_payment_and_lien_clocks",
    ],
    # No engine rule set reads California law yet; the bill itself is coded
    # in MasterFormat, the set the US country row already runs.
    validation_rule_sets=["masterformat"],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    # Left empty on purpose. The demo estate is owned elsewhere and a template
    # id claimed here would fight whatever that work lands.
    demo_template_ids=[],
    branding=PartnerBranding(
        primary_color="#1D4E89",  # California state blue
        accent_color="#FFB81C",  # California state gold
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "US",
        "country_name_en": "United States",
        "subdivision": "US-CA",
        "subdivision_name_en": "California",
        "region_focus": "California (US-CA)",
        "backend_module": "oe_us_ca_pack",
        "parent_pack": "us-costdata",
        "regulator_refs": [
            "California Revenue and Taxation Code, Parts 1, 1.5 and 1.6 (sales, use and district taxes)",
            "18 California Code of Regulations § 1521 (Construction Contractors)",
            "California Labor Code §§ 1720 to 1861 (Public Works and Public Agencies)",
            "California Labor Code § 1725.5 (contractor registration for public works)",
            "California Public Contract Code § 7201 (public works retention cap)",
            "California Public Contract Code § 7107 (release of retention)",
            "California Public Contract Code § 20104.50 (local agency progress payments)",
            "California Civil Code § 8811 (private works retention cap, from 1 January 2026)",
            "California Civil Code §§ 8200, 8412, 8414 and 8460 (mechanics lien)",
            "California Business and Professions Code § 7108.5 (payment to subcontractors)",
        ],
        # The rules the application actually reads live in the backend module
        # named above. These are the codes it serves, listed here so the pack
        # page can say what activating it brings without duplicating any number.
        "state_rule_topics": [
            "sales_tax",
            "prevailing_wage",
            "retainage",
            "prompt_payment",
            "lien",
        ],
        "payment_clock_regimes": ["us_ca_public_20104", "us_ca_private_8800"],
        "state_general_contractor_licence": True,
        "support_email": "info@datadrivenconstruction.io",
    },
)
