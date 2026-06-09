"""Build the ``PartnerPackManifest`` instance for the us-rsmeans pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="us-rsmeans",
    partner_name="US Construction Pack",
    partner_url=None,
    pack_version="0.2.0",
    description=(
        "Pre-configured for US general contractors: CSI MasterFormat 2020 + "
        "UniFormat II elemental, AIA A201-2017 General Conditions + Owner-"
        "Contractor agreement family (A101/A102/A103/A104/A141), OSHA 29 CFR "
        "1926 construction safety, IBC 2021 building code, and RSMeans City "
        "Cost Index for 720+ US metros."
    ),
    default_locale="en-US",
    additional_locales={"en-US": "locales/en-US.json"},
    cwicr_regions=[
        # Note: only one CWICR pack exists for the US (national-average USD
        # with regional adjustment factors). RSMeans CCI is applied on top
        # for per-metro localization. The cities are listed under
        # ``metadata.rsmeans_cci_cities`` for the onboarding wizard.
        "cwicr-usa-usd",
    ],
    default_currency="USD",
    default_tax_template="us_state_sales_tax",
    validation_rule_packs=[
        "masterformat_2020",
        "uniformat_ii_e1557",
        "aia_a201_2017",
        "aia_owner_contractor",
        "osha_1926",
        "ibc_2021",
        "rsmeans_city_index",
    ],
    default_modules=[],   # empty = show all
    hidden_modules=[],
    demo_template_ids=["medical-us"],
    branding=PartnerBranding(
        primary_color="#0A3161",   # Old Glory blue
        accent_color="#B31942",    # Old Glory red
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,      # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "US",
        "country_name_en": "United States",
        "regulator_refs": [
            "CSI MasterFormat 2020",
            "ASTM E1557-09 UniFormat II",
            "AIA A201-2017 General Conditions",
            "AIA A101/A102/A103/A104/A141 (Owner-Contractor family)",
            "OSHA 29 CFR 1926 (Construction Industry)",
            "IBC 2021 (International Building Code)",
            "ICC A117.1-2017 (Accessibility)",
            "IECC 2021 (Energy)",
            "RSMeans CCI",
        ],
        "rsmeans_cci_cities": [
            # Top-10 US metros pre-offered in the onboarding wizard.
            # Full RSMeans CCI covers 720+ US cities + ~80 Canadian cities;
            # users can add more from the cost-database UI.
            {"slug": "ny-new-york",     "label": "New York, NY",      "metro": "NYC",   "default": True},
            {"slug": "ca-los-angeles",  "label": "Los Angeles, CA",   "metro": "LA",    "default": False},
            {"slug": "il-chicago",      "label": "Chicago, IL",       "metro": "CHI",   "default": False},
            {"slug": "tx-houston",      "label": "Houston, TX",       "metro": "HOU",   "default": False},
            {"slug": "ma-boston",       "label": "Boston, MA",        "metro": "BOS",   "default": False},
            {"slug": "dc-washington",   "label": "Washington, DC",    "metro": "DC",    "default": False},
            {"slug": "ca-san-francisco","label": "San Francisco, CA", "metro": "SF",    "default": False},
            {"slug": "ga-atlanta",      "label": "Atlanta, GA",       "metro": "ATL",   "default": False},
            {"slug": "wa-seattle",      "label": "Seattle, WA",       "metro": "SEA",   "default": False},
            {"slug": "co-denver",       "label": "Denver, CO",        "metro": "DEN",   "default": False},
        ],
        "state_license_authorities": {
            # Per-state general-contractor licensing authority — surfaced
            # in the onboarding ``state_license_number`` help text.
            "CA": "California State Licensing Board (CSLB)",
            "FL": "Florida Construction Industry Licensing Board (CILB)",
            "NY": "NYC Department of Buildings (DOB), city-issued",
            "TX": "Texas Dept. of Licensing & Regulation (TDLR), no state GC license",
            "VA": "Virginia DPOR Board for Contractors",
            "WA": "Washington L&I Contractor Registration",
            "MA": "Massachusetts CSL / HIC",
            "GA": "Georgia State Licensing Board for Residential & General Contractors",
            "IL": "Illinois, municipal licensing only (Chicago DOB)",
            "OR": "Oregon Construction Contractors Board (CCB)",
        },
        "ibc_state_adoptions": {
            # State-level IBC editions currently adopted (as of pack release).
            "CA": "2022 California Building Code (CBC), based on IBC 2021",
            "NY": "2020 New York City Building Code, based on IBC 2015 with NYC amendments",
            "FL": "Florida Building Code 8th Edition (2023), based on IBC 2021",
            "TX": "IBC 2021, municipal adoption",
            "MA": "780 CMR 9th Edition, based on IBC 2015 + Massachusetts amendments",
        },
        "support_email": "info@datadrivenconstruction.io",
    },
)
