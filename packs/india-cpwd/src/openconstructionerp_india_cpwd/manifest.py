"""Build the ``PartnerPackManifest`` instance for the india-cpwd pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="india-cpwd",
    partner_name="India Construction Pack",
    partner_url=None,
    pack_version="0.2.0",
    description=(
        "Pre-configured for Indian general contractors, PSUs and private "
        "developers: CPWD Specifications 2019 + Works Manual 2019, "
        "CPWD DSR 2023, full IS-codes bundle (456, 800, 1893, 875, 13920), "
        "NBC 2016 with 2024 amendments, RERA 2016, GST + TDS u/s 194C + "
        "BOCW labour cess. English + Hindi UI."
    ),
    default_locale="en",
    additional_locales={
        "hi": "locales/hi.json",
    },
    cwicr_regions=[
        # Top 7 Indian metros — pre-loaded for instant project setup
        "cwicr-eng-delhi",       # Delhi NCR (default for DSR)
        "cwicr-eng-mumbai",      # Maharashtra
        "cwicr-eng-bangalore",   # Karnataka
        "cwicr-eng-chennai",     # Tamil Nadu
        "cwicr-eng-hyderabad",   # Telangana
        "cwicr-eng-kolkata",     # West Bengal
        "cwicr-eng-pune",        # Maharashtra (industrial belt)
    ],
    default_currency="INR",
    default_tax_template="in_gst_18",
    validation_rule_packs=[
        # Specifications & rates
        "cpwd_specs_2019",          # CPWD Specs 2019 + Works Manual 2019 + DSR 2023
        "dsr_delhi_rates",           # DSR 2023 unit-rate alignment
        # Structural codes
        "is_456_concrete",           # IS 456:2000 + amendments
        "is_800_steel",              # IS 800:2007 limit-state
        "is_seismic_loads",          # IS 1893 + IS 875 + IS 13920 bundle
        # Building code (broader than CPWD DSR)
        "nbc_india_2016",            # NBC 2016 + 2024 amendments
        # Real-estate regulation (private developers)
        "rera_2016",                 # RERA Act 2016
        # Tax & statutory
        "india_tax_construction",    # GST + TDS 194C + BOCW labour cess
    ],
    default_modules=[],   # empty = show all (Shape A - no module hiding)
    hidden_modules=[],
    demo_template_ids=["govt-building-delhi"],
    branding=PartnerBranding(
        primary_color="#FF9933",   # Saffron (Indian flag, Kesari)
        accent_color="#138808",    # India Green (Indian flag)
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,      # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "IN",
        "country_name_en": "India",
        "country_name_hi": "भारत",
        "regulator_refs": [
            "CPWD Specifications 2019 (Vols. I & II)",
            "CPWD Works Manual 2019",
            "CPWD DSR 2023 (Delhi Schedule of Rates)",
            "IS 456:2000 (Concrete) + amendments",
            "IS 800:2007 (Steel)",
            "IS 1893-1:2016 (Seismic) + Parts 2-5",
            "IS 875 Parts 1-5:1987 (Loads)",
            "IS 13920:2016 (Ductile Detailing)",
            "NBC 2016 + 2024 amendments",
            "RERA Act 2016",
            "CGST/SGST/IGST Act",
            "Income-Tax Act s.194C (TDS on contractors)",
            "BOCW Cess Act 1996 (labour cess 1%)",
        ],
        # CPWD = central PWD only. State works follow state-specific SoRs.
        # Top 5 state SoRs flagged in onboarding as separately-enableable.
        "compatible_state_sors": [
            "mppwd",            # Madhya Pradesh PWD
            "rpwd",             # Rajasthan PWD
            "mjp",              # Maharashtra Jeevan Pradhikaran
            "kerala_pwd",       # Kerala PWD
            "tamilnadu_pwd",    # Tamil Nadu PWD
        ],
        "compatible_state_sors_note": (
            "CPWD is central-only. State PWD works need the matching state "
            "SoR enabled separately — the onboarding wizard prompts the user "
            "to select the predominant work type so the right SoR is loaded."
        ),
        "cwicr_metros_preloaded": [
            "Delhi NCR",
            "Mumbai",
            "Bangalore",
            "Chennai",
            "Hyderabad",
            "Kolkata",
            "Pune",
        ],
        "dsr_reference_year": 2023,
        "nbc_amendment_year": 2024,
        "support_email": "info@datadrivenconstruction.io",
    },
)
