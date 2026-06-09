"""BIM-Cluster Hessen partner pack manifest.

Pre-configures OpenConstructionERP for German BIM consultancies and
engineering offices, especially those active in Hessen (Frankfurt /
Wiesbaden / Kassel / Darmstadt). Loads the German standards stack:

* DIN 276:2018-12     — Kostengruppen KG 100–800
* GAEB DA XML 3.3     — X83 Angebotsabgabe / X84 Nebenangebot / X86 Auftragserteilung
* VOB/A + VOB/B + VOB/C 2019  — Vergabe, Vertragsbedingungen, ATVs (DIN 18299 ff.)
* ISO 19650-1/-2      — BIM Information Management (CDE, BEP, MIDP/TIDP, EIR)
* BKI Baukosten        — Plausibilitäts-Benchmarks pro KG / Gebäudetyp / Region
* HOAI 2013/2021      — Leistungsphasen 1–9, Honorarzone, Anrechenbare Kosten
* LV-Qualität          — Leistungsverzeichnis-spezifisches BOQ-Quality-Set
                          (Titel → Position → Teilleistung)
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="bimhessen-de",
    partner_name="BIM-Cluster Hessen",
    partner_url="https://bim-cluster-hessen.com",
    pack_version="0.2.0",
    description=(
        "Vorkonfiguriert für deutsche BIM-Beratungs- und Ingenieurbüros: "
        "DIN 276, GAEB X83/X84/X86, VOB/A+B+C, ISO 19650 CDE, BKI Benchmarks, "
        "HOAI 2021 Leistungsphasen und LV-Qualitätsregeln."
    ),
    default_locale="de",
    additional_locales={"de": "locales/de.json"},
    # Note: CWICR Hessen (Frankfurt / Kassel) is not yet published.
    # The only DACH region in the v3 catalogue is DE_BERLIN. BKI regional
    # factors for DE-HE are applied via the bki_benchmarks rule pack.
    cwicr_regions=["cwicr-de-berlin"],
    default_currency="EUR",
    default_tax_template="de_vat_19",
    validation_rule_packs=[
        "din_276",
        "gaeb_x83_x86",
        "vob_2019",
        "iso_19650_cde",
        "bki_benchmarks",
        "hoai_2021_fees",
        "lv_leistungsverzeichnis_quality",
    ],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["residential-berlin"],
    branding=PartnerBranding(
        primary_color="#0C9CB7",  # BIM-Cluster Hessen teal
        accent_color="#7A7A7A",  # BIM-Cluster Hessen grey
        logo_path="logo.png",
        favicon_path=None,
        powered_by_text="Powered by OpenConstructionERP, in partnership with BIM-Cluster Hessen",
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "DE",
        "country_name_en": "Germany",
        "region_focus": "Hessen (DE-HE)",
        "regulator_refs": [
            "DIN 276:2018-12",
            "GAEB DA XML 3.3",
            "VOB/A 2019",
            "VOB/B 2019",
            "VOB/C 2019 (DIN 18299 ff.)",
            "ISO 19650-1:2018",
            "ISO 19650-2:2018",
            "HOAI 2021 (BGBl. I S. 2792)",
            "BKI Baukosten",
        ],
        "cwicr_gap": (
            "Hessen-spezifische CWICR-Region (Frankfurt am Main) noch nicht "
            "veröffentlicht — fällt auf cwicr-de-berlin zurück; "
            "BKI-Regionalfaktor DE-HE wird angewendet."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
