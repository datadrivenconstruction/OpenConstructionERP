"""Build the ``PartnerPackManifest`` instance for the nzs pack."""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="nzs",
    partner_name="New Zealand Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    description=(
        "Pre-configured for New Zealand contractors: New Zealand Building "
        "Code (NZBC) clauses B1/B2/E2/H1, NZS 3604:2011 timber-framed "
        "buildings, NZS 3910:2023 Conditions of Contract (replaces 2013 ed.), "
        "MBIE Acceptable Solutions and Rawlinsons New Zealand Construction "
        "Handbook. Defaults to NZD and 15% GST."
    ),
    default_locale="en-NZ",
    additional_locales={
        "en-NZ": "locales/en-NZ.json",
    },
    cwicr_regions=[
        # Only published bases are declared: a slug that resolves to nothing
        # was listed on the activation dialog and then skipped at install.
        # Wellington and Christchurch follow when their bases are.
        "cwicr-eng-auckland",
    ],
    default_currency="NZD",
    default_tax_template="nz_gst_15",
    # Was absent, which is not the same as deliberately empty: a project made
    # under this pack opened on the flat international default while the pack
    # itself declared NZD, the NZ cost regions and the NZ standards.
    #
    # The New Zealand template is still the neutral international method
    # carrying NZD and 15 percent GST rather than a national convention, and it
    # says so in its own description. Naming it here is worth doing anyway, and
    # it turns national by itself once the markup table states the NZ stack.
    default_methodology="new_zealand",
    validation_rule_packs=[
        "nzbc_acceptable_solutions",
        "nzs_3604_timber",
        "nzs_3910_2023_contracts",
        "rawlinsons_nz_benchmarks",
    ],
    default_modules=[],
    hidden_modules=[],
    branding=PartnerBranding(
        primary_color="#000000",  # NZ all-black
        accent_color="#C8102E",  # NZ silver-fern red accent
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "NZ",
        "country_name_en": "New Zealand",
        "country_name_mi": "Aotearoa",
        "iso_3166_1_alpha_2": "NZ",
        "gst_rate_pct": 15.0,
        "measurement_system": "metric",
        "regulator_refs": [
            "NZBC — New Zealand Building Code (MBIE)",
            "NZS 3604:2011 Timber-framed buildings",
            "NZS 3910:2023 Conditions of Contract for Building and Civil Engineering Construction (replaces NZS 3910:2013)",
            "NZS 3915:2005 Conditions of Contract — no Engineer (rare, civil only)",
            "MBIE Acceptable Solutions B1/AS1, B2/AS1, E2/AS1, H1/AS1",
            "Rawlinsons New Zealand Construction Handbook",
        ],
        "practitioner_licence": "LBP — Licensed Building Practitioner (MBIE)",
        "lbp_classes": [
            "Design 1/2/3",
            "Carpentry",
            "Bricklaying & Blocklaying",
            "External Plastering",
            "Foundations",
            "Roofing",
            "Site",
        ],
        "default_contract": "NZS 3910:2023",
        "support_email": "info@datadrivenconstruction.io",
    },
)
