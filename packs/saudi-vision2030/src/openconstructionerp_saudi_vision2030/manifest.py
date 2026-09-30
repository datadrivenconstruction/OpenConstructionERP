"""Build the ``PartnerPackManifest`` instance for the saudi-vision2030 pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.

Saudi Vision 2030 pack — pre-configures OCERP for KSA mega-project
contractors (NEOM, Red Sea Global, Diriyah Gate, Qiddiya, RCJY, Aramco
EPC). Loads the full Saudi standards stack:

  * SBC 2018 (Saudi Building Code), split per-Part:
        SBC 201  — Energy Conservation
        SBC 301  — Loads & structural design
        SBC 304  — Concrete
        SBC 401  — Electrical
        SBC 501  — Mechanical (HVAC + Plumbing)
        SBC 801  — Fire Code (with Civil Defense)
  * MoMRAH — municipal urban planning + Balady permit portal
  * Saudi Aramco — SAES / SAMSS / GES (engineering & materials), 9COM
        Schedule Q, PIM vendor pre-qualification, AVL, IKTVA, approval chain
  * NEOM — net-zero, no-ICE, 15-minute city, subzone-aware standards
  * Saudization (Nitaqat) — workforce localisation band gates
  * ISO 19650 — BIM information management (adopted by NEOM / RCJY / Aramco)
  * Vision 2030 KPIs — IKTVA, Saudi Green Initiative, water/energy/waste
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="saudi-vision2030",
    partner_name="Saudi Vision 2030 Pack",
    partner_url=None,
    pack_version="0.2.0",
    description=(
        "Pre-configured for Saudi Arabian mega-projects: full SBC 2018 stack "
        "(per-Part: 201 / 301 / 304 / 401 / 501 / 801), MoMRAH & Balady, "
        "Saudi Aramco SAES + SAMSS + 9COM, NEOM net-zero standards, "
        "Saudization (Nitaqat), ISO 19650 BIM, Vision 2030 KPIs. "
        "Bilingual Arabic (RTL) + English."
    ),
    default_locale="ar",
    additional_locales={
        "ar": "locales/ar.json",
    },
    # No Saudi base is published yet, so none is declared. Riyadh, then
    # Jeddah, Dammam, NEOM/Tabuk, Makkah, Madinah and Khobar, follow when
    # their bases are; a declared slug that resolves to nothing was listed
    # on the activation dialog and then skipped at install.
    cwicr_regions=[],
    default_currency="SAR",
    default_tax_template="sa_vat_15",
    # The GCC preliminaries-and-general cascade the catalogue builds for Saudi
    # Arabia from the GULF regional markup stack. Left empty until now, which
    # put every project created under this pack on the flat international
    # method while the pack advertised the Saudi Building Code and the Aramco
    # stack around it.
    default_methodology="saudi_arabia",
    validation_rule_packs=[
        # Saudi Building Code 2018 — split per-Part for selective enablement.
        "sbc_201_energy",
        "sbc_301_loads",
        "sbc_304_concrete",
        "sbc_401_electrical",
        "sbc_501_mechanical",
        "sbc_801_fire",
        # Municipal / urban planning.
        "momrah_urban_planning",
        # Saudi Aramco stack.
        "aramco_saes_samss",
        "aramco_approval_chain",
        "aramco_pim_qualification",
        # NEOM authority standards.
        "neom_design_standards",
        # Saudization workforce-localisation.
        "saudization_nitaqat",
        # BIM management adopted by KSA mega-projects.
        "iso_19650_bim",
        # Vision 2030 cross-cutting KPIs.
        "vision_2030_kpis",
    ],
    default_modules=[],  # empty = show all modules in sidebar
    hidden_modules=[],
    branding=PartnerBranding(
        primary_color="#006C35",  # Saudi flag green (Pantone 354 C)
        accent_color="#FFFFFF",  # white
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "SA",
        "country_name_en": "Kingdom of Saudi Arabia",
        "country_name_ar": "المملكة العربية السعودية",
        "writing_direction": "rtl",
        "regulator_refs": [
            "SBC 2018 (Saudi Building Code) — SBC 201/301/304/401/501/801",
            "MoMRAH (Ministry of Municipal, Rural Affairs and Housing)",
            "Balady building-permit E-service",
            "Saudi Aramco SAES / SAMSS / GES",
            "Saudi Aramco 9COM Schedule Q + PIM + AVL",
            "Nitaqat (Ministry of HRSD)",
            "ZATCA (Zakat, Tax and Customs Authority) — 15% VAT",
            "ISO 19650-1/-2/-5 (BIM information management)",
            "NEOM Design Standards (THE LINE / Oxagon / Trojena / Sindalah / Magna)",
            "Royal Commission for Jubail and Yanbu (RCJY)",
            "Royal Commission for Riyadh City (RCRC)",
            "Saudi Green Initiative (SGI) — net-zero 2060",
            "Saudi Vision 2030 — National Transformation Programme",
        ],
        "target_clients": [
            "NEOM developments",
            "Red Sea Global / AMAALA",
            "Diriyah Gate Development Authority",
            "Qiddiya Investment Company",
            "Public Investment Fund (PIF) giga-projects",
            "Saudi Aramco EPC contractors",
            "MoMRAH municipal projects",
        ],
        "supported_regions": [
            "Riyadh",
            "Jeddah",
            "Makkah",
            "Madinah",
            "Dammam",
            "Khobar",
            "Eastern Province",
            "NEOM / Tabuk",
            "Abha / Asir",
            "Hail",
            "Qassim",
            "Jazan",
        ],
        "cwicr_seed_gap": (
            "Only cwicr-eng-riyadh is currently seeded in the v3 catalogue. "
            "Jeddah / Dammam / NEOM / Makkah / Madinah cost regions are "
            "surfaced in onboarding and resolve through the marketplace "
            "import when the user opts in."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
