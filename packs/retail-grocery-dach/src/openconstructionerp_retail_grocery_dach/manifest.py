"""Discount grocery retail pack (DACH) manifest.

Industry pack that pre-configures OpenConstructionERP for German-speaking
discount food-retail new-builds. It ships three fully priced example
projects (Heilbronn, Heidelberg, Karlsruhe), each a DIN 276 cost plan with
a complete Leistungsverzeichnis across the retail trades (shell, roof,
facade, drywall and interior fit-out, mechanical, CO2 refrigeration,
electrical, photovoltaics, external works and store fit-out), plus the
DACH standards stack (DIN 276, GAEB DA XML 3.3, LV quality and BKI
plausibility benchmarks). EUR with 19 percent VAT.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="retail-grocery-dach",
    partner_name="Discount Grocery Retail (DACH)",
    partner_url=None,
    pack_type="industry",
    pack_version="0.1.0",
    description=(
        "Branchenpaket fuer den Lebensmittel-Discountmarkt im DACH-Raum: "
        "drei vollstaendig bepreiste Beispielprojekte (Heilbronn, Heidelberg "
        "und Karlsruhe) als Kostenberechnung nach DIN 276 mit komplettem "
        "Leistungsverzeichnis ueber alle Gewerke, GAEB DA XML 3.3, "
        "LV-Qualitaet und BKI-Plausibilitaetsbenchmarks. EUR, 19 % MwSt."
    ),
    default_locale="de",
    cwicr_regions=["cwicr-de-berlin"],
    default_currency="EUR",
    default_tax_template="de_vat_19",
    validation_rule_packs=[
        "din_276",
        "gaeb_x83_x86",
        "lv_leistungsverzeichnis_quality",
        "bki_benchmarks",
    ],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=[
        "retail-market-heilbronn",
        "retail-market-heidelberg",
        "retail-market-karlsruhe",
    ],
    branding=PartnerBranding(
        primary_color="#2E7D32",  # neutral fresh-market green
        accent_color="#9E9E9E",  # neutral grey
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text="OpenConstructionERP retail grocery pack (DACH)",
    ),
    onboarding_script_path=None,
    metadata={
        "industry": "retail-grocery",
        "industry_name_en": "Discount food retail",
        "region_focus": "DACH (DE/AT/CH)",
        "regulator_refs": [
            "DIN 276:2018-12",
            "GAEB DA XML 3.3",
            "VOB/C 2019 (DIN 18299 ff.)",
            "BKI Baukosten",
        ],
        "demo_projects": [
            "retail-market-heilbronn",
            "retail-market-heidelberg",
            "retail-market-karlsruhe",
        ],
        "support_email": "info@datadrivenconstruction.io",
    },
)
