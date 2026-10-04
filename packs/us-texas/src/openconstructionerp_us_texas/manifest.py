"""Build the ``PartnerPackManifest`` instance for the us-texas pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="us-texas",
    partner_name="Texas Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "State depth for Texas on top of the US pack: the sales tax split "
        "between a lump sum and a separated contract and the reversal of that "
        "rule for nonresidential repair work, locally determined prevailing "
        "wage with no state schedule, the two public works retainage caps and "
        "the contract value that switches between them, and the statutory "
        "payment and lien clocks for public and private work."
    ),
    default_locale="en-US",
    # No locale file of its own. en-US is a core locale and the national pack
    # already carries the US construction vocabulary; a Texas copy of those
    # hundred keys would only give the tree somewhere to drift. Texas changes
    # the rules, not the words.
    additional_locales={},
    # There is no Texas-specific CWICR pack. The national USD pack is the cost
    # region; the city cost index carried by us-costdata localises it per metro.
    cwicr_regions=["cwicr-usa-usd"],
    default_currency="USD",
    default_tax_template="us_state_sales_tax",
    default_methodology="united_states",
    validation_rule_packs=[
        "tx_sales_tax_contracts",
        "tx_prevailing_wage_2258",
        "tx_retainage_2252",
        "tx_payment_and_lien_clocks",
    ],
    # No engine rule set reads Texas law yet; the bill itself is coded in
    # MasterFormat, the set the US country row already runs.
    validation_rule_sets=["masterformat"],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    # Left empty on purpose. The demo estate is owned elsewhere and a template
    # id claimed here would fight whatever that work lands.
    demo_template_ids=[],
    branding=PartnerBranding(
        primary_color="#002868",  # Texas flag blue
        accent_color="#BF0A30",  # Texas flag red
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "US",
        "country_name_en": "United States",
        "subdivision": "US-TX",
        "subdivision_name_en": "Texas",
        "region_focus": "Texas (US-TX)",
        "backend_module": "oe_us_tx_pack",
        "parent_pack": "us-costdata",
        "regulator_refs": [
            "Texas Tax Code Chapter 151 (Limited Sales, Excise and Use Tax)",
            "34 Texas Administrative Code §§ 3.291 and 3.357 (Comptroller construction rules)",
            "Texas Government Code Chapter 2258 (Prevailing Wage Rates)",
            "Texas Government Code Chapter 2252, Subchapter B (Retainage on public works)",
            "Texas Government Code Chapter 2251 (Prompt Payment, public)",
            "Texas Property Code Chapter 28 (Prompt Payment, private)",
            "Texas Property Code Chapter 53 (Mechanic's, Contractor's or Materialman's Lien)",
            "Texas Constitution, Article VIII, Section 24-a (no individual income tax)",
        ],
        # The rules the application actually reads live in the backend module
        # named above. These are the codes it serves, listed here so the pack
        # page can say what activating it brings without duplicating any number.
        "state_rule_topics": [
            "sales_tax",
            "income_tax",
            "prevailing_wage",
            "retainage",
            "prompt_payment",
            "lien",
        ],
        "payment_clock_regimes": ["us_tx_public_2251", "us_tx_private_ch28"],
        "state_general_contractor_licence": False,
        "support_email": "info@datadrivenconstruction.io",
    },
)
