"""Build the ``PartnerPackManifest`` instance for the aus pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="aus",
    partner_name="Australia Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    description=(
        "Pre-configured for Australian general contractors: National "
        "Construction Code (NCC) 2022, AS 1684 timber-framing (Parts 1-4), "
        "AS 3600 concrete, AS 4100 steel, AS 4000-1997 / AS 4902-2000 "
        "contract suite, Rawlinsons Australian Construction Handbook 2024. "
        "Defaults to AUD and 10% GST."
    ),
    default_locale="en-AU",
    additional_locales={
        "en-AU": "locales/en-AU.json",
    },
    cwicr_regions=[
        # Only published bases are declared: a slug that resolves to nothing
        # was listed on the activation dialog and then skipped at install.
        # Melbourne, Brisbane, Perth and Adelaide follow when their bases are.
        "cwicr-eng-sydney",
    ],
    default_currency="AUD",
    default_tax_template="au_gst_10",
    default_methodology="australia",
    validation_rule_packs=[
        "ncc_2022",
        "as_1684_timber",
        "as_3600_concrete",
        "as_4100_steel",
        "as_4000_contracts",
        "rawlinsons_benchmarks",
    ],
    # The documents above are reference text the engine never executes. This
    # is the list that switches rules on. Australian quantity surveying follows
    # the Commonwealth NRM lineage, which is also what the classification
    # registry and the AU country row give an Australian project, so a project
    # created under the pack runs the same national checks as one created
    # without it.
    validation_rule_sets=["nrm"],
    default_modules=[],  # empty = show all (Shape A, no module hiding)
    hidden_modules=[],
    # Two Australian (AUD, NCC 2022 / AS-standards) demos so the pack always
    # lands two in-market projects: the Sydney mixed-use flagship plus the
    # Melbourne hyperscale data centre (major AU industrial / infrastructure).
    demo_template_ids=["mixed-use-sydney", "data-center-melbourne"],
    branding=PartnerBranding(
        primary_color="#00843D",  # Australian green (Wattle/Gold pair)
        accent_color="#FFCD00",  # Australian gold
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "AU",
        "country_name_en": "Australia",
        "iso_3166_1_alpha_2": "AU",
        "gst_rate_pct": 10.0,
        "measurement_system": "metric",
        "regulator_refs": [
            "NCC 2022 (National Construction Code Vol 1+2+3) — ABCB",
            "AS 1684.1-4 Residential timber-framed construction",
            "AS 3600-2018 Concrete structures",
            "AS 4100-2020 Steel structures",
            "AS 4000-1997 General conditions of contract",
            "AS 4902-2000 General conditions of contract for D&C",
            "AS 4910 Precast concrete components",
            "Rawlinsons Australian Construction Handbook 2024",
        ],
        "builder_licence_per_state": {
            "NSW": "NSW Fair Trading — Building Licence",
            "VIC": "VBA (Victorian Building Authority) — Registered Building Practitioner",
            "QLD": "QBCC (Queensland Building and Construction Commission) — Builder Licence",
            "WA": "Building Commission WA — Builder Registration",
            "SA": "CBS (Consumer and Business Services) — Building Work Contractor",
            "TAS": "CBOS (Consumer, Building and Occupational Services)",
            "ACT": "Access Canberra — Construction Occupations Licence",
            "NT": "NT Building Practitioners Board",
        },
        "default_contract": "AS 4000-1997",
        "support_email": "info@datadrivenconstruction.io",
    },
)
