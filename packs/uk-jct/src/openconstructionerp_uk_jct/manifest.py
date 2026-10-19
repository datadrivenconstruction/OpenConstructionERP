"""Build the ``PartnerPackManifest`` instance for the uk-jct pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="uk-jct",
    partner_name="UK Construction Pack",
    partner_url=None,
    pack_version="0.3.0",
    description=(
        "Pre-configured for UK contracting: RICS NRM measurement and cost planning, the JCT "
        "contract suite, the Construction Act payment regime, CIS and the VAT domestic reverse "
        "charge, CDM 2015 and the Building Safety Act 2022."
    ),
    default_locale="en-GB",
    additional_locales={
        "en-GB": "locales/en-GB.json",
    },
    cwicr_regions=[
        # The UK-wide CWICR slug is the one that exists in the marketplace.
        # Regional adjustment is done in-app with a location factor rather
        # than by shipping a slug per city.
        "cwicr-uk-gbp",
    ],
    default_currency="GBP",
    default_tax_template=None,
    default_methodology="united_kingdom",
    validation_rule_packs=[
        "nrm_1_cost_planning",
        "nrm_2_detailed_measurement",
        "nrm_3_maintenance",
        "jct_contract_suite",
        "construction_act_payments",
        "uk_tax_and_cis",
        "cost_benchmarking",
        "cdm_2015",
        "bsa_2022",
    ],
    # The engine rule sets behind those documents. "nrm" is the method of
    # measurement and travels wherever the method is used; "uk_statutory" is
    # the law of one country and asks what the estimate records about itself,
    # which is why it is a set of its own rather than more NRM rules.
    validation_rule_sets=[
        "nrm",
        "uk_statutory",
    ],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    branding=PartnerBranding(
        primary_color="#012169",  # Union flag blue
        accent_color="#C8102E",  # Union flag red
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "GB",
        "country_name_en": "United Kingdom",
        "regulator_refs": [
            "RICS NRM 1, order of cost estimating and cost planning for capital building works",
            "RICS NRM 2, detailed measurement for building works",
            "RICS NRM 3, order of cost estimating and cost planning for building maintenance works",
            "JCT standard forms of building contract",
            "Housing Grants, Construction and Regeneration Act 1996, as amended",
            "Construction Industry Scheme, Finance Act 2004 Part 3 Chapter 3",
            "VAT domestic reverse charge for building and construction services",
            "Construction (Design and Management) Regulations 2015",
            "Building Safety Act 2022",
        ],
        "support_email": "info@datadrivenconstruction.io",
        # The four jurisdictions, because they are not one. Building control,
        # the safety regime and parts of the payment legislation differ across
        # them, and a pack that lists cities implies a cost region per city
        # that this pack does not ship. What it ships is the UK-wide cost
        # region plus a location factor the user applies.
        "jurisdictions": [
            "England",
            "Wales",
            "Scotland",
            "Northern Ireland",
        ],
        "jurisdiction_note": (
            "The Building Safety Act gateway regime and the reformed building control regime are "
            "England only. CDM 2015 covers Great Britain, with a separate Northern Ireland regime. "
            "The Construction Act applies across Great Britain, with Northern Ireland having its own "
            "order to the same effect. Scots law governs contracts in Scotland and the JCT forms are "
            "used there with Scottish supplements."
        ),
    },
)
