"""Build the ``PartnerPackManifest`` instance for the romania-ro pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="romania-ro",
    partner_name="Romania Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Romanian contractors, designers and public "
        "clients: every line filed under the deviz general chapters of "
        "HG 907/2016 and classified against DIN 276, RON currency with "
        "21% TVA, the Romanian cost cascade (indirect costs, profit, "
        "contingency), public procurement under Legea 98/2016 and the "
        "building permit references. Romanian and English interface."
    ),
    default_locale="ro",
    additional_locales={},
    cwicr_regions=[
        "cwicr-ro-bucharest",  # resolves to RO_BUCHAREST
    ],
    default_currency="RON",
    # Documentation only, as on every pack: the rate a bill is charged comes
    # from the dated tax seed for the project's country, and the methodology
    # template carries the same 21 for the cascade.
    default_tax_template="ro_tva_21",
    default_methodology="romania",
    validation_rule_packs=[
        "ro_deviz_general",
        "ro_achizitii_publice",
        "ro_autorizare_constructii",
        "ro_tva_constructii",
    ],
    # The engine identifier. Two rules run under it: every priced line names
    # a deviz general chapter, and the chapter is one HG 907/2016 defines.
    validation_rule_sets=[
        "romania",
        "din276",
    ],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    demo_template_ids=["residential-cluj", "office-bucharest"],
    branding=PartnerBranding(
        primary_color="#002B7F",  # blue of the national flag
        accent_color="#FCD116",  # yellow of the national flag
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "RO",
        "country_name_en": "Romania",
        "country_name_ro": "România",
        "classification_standard": "din276",
        "national_classification_key": "deviz",
        "measurement_system": "metric",
        "regulator_refs": [
            "HG 907/2016 (etapele de elaborare și conținutul-cadru al documentațiilor tehnico-economice, deviz general)",
            "Legea 98/2016 privind achizițiile publice, and HG 395/2016 (implementing norms)",
            (
                "Legea 169/2026, Codul amenajării teritoriului, urbanismului și construcțiilor (in force 25.08.2026, "
                "replaces Legea 50/1991 on building permits)"
            ),
            "Legea 10/1995 privind calitatea în construcții (partly repealed by Legea 169/2026)",
            "Legea 227/2015, Codul fiscal: art. 291 (TVA rates), art. 331 (domestic reverse charge)",
            "P100-1/2013, Cod de proiectare seismică (Ordin MDRAP 2465/2013)",
        ],
        "vat_standard_rate": 21,
        "vat_reduced_rate": 11,
        "review_status": (
            "Currency, tax and regulatory references are drawn from public "
            "sources cited in the README. Pending review by a Romanian cost "
            "engineer before they are relied on for a public tender."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
