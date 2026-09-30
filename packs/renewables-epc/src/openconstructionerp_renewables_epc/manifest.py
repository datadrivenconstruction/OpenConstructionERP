"""Build the ``PartnerPackManifest`` instance for the renewables-epc pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="renewables-epc",
    partner_name="Renewables EPC Pack",
    partner_url=None,
    pack_version="0.2.0",
    description=(
        "Pre-configured for solar / wind / BESS EPC contractors: PV array "
        "takeoff, turbine BOM, MV cable schedules, LCOE templates, "
        "IEC 61400 (wind) + IEC 61215 + IEC 61730 (PV) + IEC 62548 (PV array) "
        "+ NFPA 855 / IEC 62619 (BESS) + ENTSO-E RfG + IEEE 1547 grid "
        "compliance, cross-region."
    ),
    default_locale="en",
    additional_locales={},
    cwicr_regions=[
        # A euro base for a pack that prices in euros; London loaded a
        # sterling catalogue into euro projects.
        "cwicr-de-berlin",
    ],
    default_currency="EUR",
    default_tax_template=None,
    validation_rule_packs=[
        "iec_61400_wind",
        "iec_61400_wind_full",
        "iec_61730_pv",
        "pv_design_full",
        "bess_design",
        "lcoe_templates",
        "mv_cable_specs",
        "renewables_grid_compliance",
    ],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    # Cross-region pack: pin two EUR energy / heavy-civil EPC projects. The
    # solar + BESS EPC flagship plus the cast-in-place RC structure (formwork-
    # led) project - heavy civil/structural EPC works, a far better fit than the
    # country-fill default (a Berlin residential complex).
    demo_template_ids=["solar-bess-epc", "rc-structure-formwork"],
    branding=PartnerBranding(
        primary_color="#00A859",  # renewable green
        accent_color="#0072CE",  # energy blue
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "XX",
        "country_name_en": "Cross-region (Renewables EPC)",
        "regulator_refs": [
            "IEC 61400-1:2019 / -3:2019 / -12-1:2022 / -13:2015 / -21:2019 / -22:2010 / -24:2019",
            "IEC 61215-1:2021",
            "IEC 61730-1/-2:2023",
            "IEC 62548:2023",
            "IEC 60364-7-712:2017",
            "IEC 60502-1/-2:2014",
            "NFPA 855:2023 (BESS)",
            "IEC 62619:2022 / IEC 62620:2014 (Li-ion cell + battery)",
            "UL 9540 / UL 9540A (BESS)",
            "IEEE 1547-2018 / IEEE 1547.1-2020",
            "EN 50549-1/-2:2019",
            "ENTSO-E Network Code RfG (EU 2016/631)",
            "UK NG ESO Grid Code",
            "FERC Order 2222",
            "NERC PRC-024-3",
            "ISO 50001 (Energy management)",
            "NREL ATB / LBNL / BloombergNEF (LCOE methodology)",
        ],
        "support_email": "info@datadrivenconstruction.io",
    },
)
