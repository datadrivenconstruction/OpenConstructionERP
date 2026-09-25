"""Build the ``PartnerPackManifest`` instance for the ukraine-ua pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="ukraine-ua",
    partner_name="Ukraine Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Ukrainian contractors, cost engineers and public "
        "clients: every line filed under the twelve chapters of the "
        "зведений кошторисний розрахунок of the Настанова з визначення "
        "вартості будівництва (наказ Мінрегіону №281) and classified against "
        "DIN 276, UAH currency with 20% ПДВ, the cost cascade within the "
        "wartime ceilings of постанова КМУ №1512, public procurement under "
        "Закон №922-VIII and the ДБН references. Ukrainian and English "
        "interface."
    ),
    default_locale="uk",
    additional_locales={},
    # No CWICR cost database covers Ukraine yet.
    cwicr_regions=[],
    default_currency="UAH",
    # Documentation only, as on every pack: the rate a bill is charged comes
    # from the dated tax seed for the project's country, and the methodology
    # template carries the same 20 for the cascade.
    default_tax_template="ua_pdv_20",
    default_methodology="ukraine",
    validation_rule_packs=[
        "ua_nastanova_281",
        "ua_publichni_zakupivli",
        "ua_dbn_mistobuduvannia",
        "ua_pdv_budivnytstvo",
    ],
    # The engine identifier. Two rules run under it: every priced line names
    # its chapter of the summary estimate, and the chapter is one of twelve.
    validation_rule_sets=[
        "ukraine",
        "din276",
    ],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    demo_template_ids=["residential-lviv", "school-kyiv"],
    branding=PartnerBranding(
        primary_color="#0057B7",  # blue of the national flag
        accent_color="#FFD700",  # yellow of the national flag
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "UA",
        "country_name_en": "Ukraine",
        "country_name_uk": "Україна",
        "classification_standard": "din276",
        "national_classification_key": "zkr",
        "measurement_system": "metric",
        "regulator_refs": [
            (
                "Наказ Мінрегіону №281 від 01.11.2021, кошторисні норми України у будівництві "
                "(Настанова з визначення вартості будівництва), as amended by Зміни №2, №5 and №6"
            ),
            (
                "Постанова КМУ №1512 від 19.11.2025, ceilings on general production and administrative costs "
                "and profit under martial law"
            ),
            "Закон України №922-VIII «Про публічні закупівлі»",
            "Податковий кодекс України, ст. 193 (ПДВ rates)",
            "ДБН В.1.2-14:2018, Загальні принципи забезпечення надійності та конструктивної безпеки будівель і споруд",
            "ДБН В.2.2-15:2019, Житлові будинки. Основні положення",
        ],
        "vat_standard_rate": 20,
        "vat_reduced_rate": 7,
        "review_status": (
            "Currency, tax and regulatory references are drawn from public "
            "sources cited in the README. Pending review by a Ukrainian cost "
            "engineer (кошторисник) before they are relied on for a public "
            "tender."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
