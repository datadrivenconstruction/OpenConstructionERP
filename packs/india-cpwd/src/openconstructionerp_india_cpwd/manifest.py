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
    default_locale="en-IN",
    additional_locales={
        "hi": "locales/hi.json",
    },
    cwicr_regions=[
        # One Indian catalogue exists and this is its marketplace slug. The
        # list used to name seven metros; six of them resolved to nothing, and
        # the one the pack called its default, Delhi, was among them. A slug
        # with no catalogue behind it is skipped at install with no error, so
        # the pack read as if it shipped seven cities of rates and shipped
        # one. The other six are recorded under metadata as planned, which is
        # what they always were.
        "cwicr-hi-mumbai",
    ],
    default_currency="INR",
    default_tax_template="in_gst_18",
    default_methodology="india",
    validation_rule_packs=[
        # Specifications & rates
        "cpwd_specs_2019",  # CPWD Specs 2019 + Works Manual 2019 + DSR 2023
        "dsr_delhi_rates",  # DSR 2023 unit-rate alignment
        # Structural codes
        "is_456_concrete",  # IS 456:2000 + amendments
        "is_800_steel",  # IS 800:2007 limit-state
        "is_seismic_loads",  # IS 1893 + IS 875 + IS 13920 bundle
        # Building code (broader than CPWD DSR)
        "nbc_india_2016",  # NBC 2016 + 2024 amendments
        # Real-estate regulation (private developers)
        "rera_2016",  # RERA Act 2016
        # Tax & statutory
        "india_tax_construction",  # GST + TDS 194C + BOCW labour cess
    ],
    # The engine identifier behind the CPWD specification document above.
    validation_rule_sets=[
        "cpwd",
    ],
    default_modules=[],  # empty = show all (Shape A - no module hiding)
    hidden_modules=[],
    demo_template_ids=["govt-building-delhi"],
    branding=PartnerBranding(
        primary_color="#FF9933",  # Saffron (Indian flag, Kesari)
        accent_color="#138808",  # India Green (Indian flag)
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
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
        # CPWD is central PWD only. State works follow state-specific SoRs.
        # Top 5 state SoRs flagged in onboarding as separately-enableable.
        "compatible_state_sors": [
            "mppwd",  # Madhya Pradesh PWD
            "rpwd",  # Rajasthan PWD
            "mjp",  # Maharashtra Jeevan Pradhikaran
            "kerala_pwd",  # Kerala PWD
            "tamilnadu_pwd",  # Tamil Nadu PWD
        ],
        "compatible_state_sors_note": (
            "CPWD is central-only. State PWD works need the matching state "
            "SoR enabled separately. The onboarding wizard prompts the user "
            "to select the predominant work type so the right SoR is loaded."
        ),
        # What actually loads, and what does not. Kept apart on purpose: the
        # single list that used to hold all seven could not tell a reader
        # which of them the install would produce.
        "cwicr_metros_available": [
            "Mumbai",
        ],
        "cwicr_metros_planned": [
            "Delhi NCR",
            "Bangalore",
            "Chennai",
            "Hyderabad",
            "Kolkata",
            "Pune",
        ],
        "cwicr_metros_planned_note": (
            "No catalogue is published for these yet. DSR is a Delhi schedule "
            "and no Delhi catalogue ships, so rates for Delhi work come from "
            "your own cost history or your own copy of the schedule."
        ),
        "dsr_reference_year": 2023,
        "nbc_amendment_year": 2024,
        "support_email": "info@datadrivenconstruction.io",
    },
)
