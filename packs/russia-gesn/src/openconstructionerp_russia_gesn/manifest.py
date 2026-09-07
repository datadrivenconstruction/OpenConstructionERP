"""Build the ``PartnerPackManifest`` instance for the russia-gesn pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="russia-gesn",
    partner_name="Russia Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Russian contractors, designers and state "
        "clients: the GESN/FER norm base and its four-part code, the "
        "resource-index method with the labour, plant and material "
        "decomposition every norm carries, overhead and estimated profit "
        "taken on payroll, the twelve-chapter summary estimate, the price "
        "level and the conversion indices that turn a base-year figure "
        "into a current one, rouble at two decimals."
    ),
    # Russian, and this one is a real choice rather than a fallback. The
    # application ships a ru bundle, so a Russian installation gets a Russian
    # interface: ``matchSupportedLanguage`` finds the locale instead of
    # answering with English. The Hungarian pack next door has to declare
    # English for exactly the opposite reason, and the difference between the
    # two is a measurement of what is on disk, not a preference.
    default_locale="ru",
    additional_locales={},
    # 55,719 items of St Petersburg cost data in roubles, already carrying the
    # GESN/FER classification this pack validates against.
    cwicr_regions=["cwicr-ru-stpetersburg"],
    default_currency="RUB",
    # Documentation only, the way every other pack's tax template is: there
    # is no tax resolver behind this field yet. The rate itself lives in the
    # methodology template, which does drive the cascade.
    default_tax_template="ru_nds_20",
    default_methodology="russia",
    validation_rule_packs=[
        # The norm base: what a code is and what stands behind it.
        "ru_gesn_fer_kody",
        "ru_resursno_indeksnyy_metod",
        # The shape of the money.
        "ru_nakladnye_smetnaya_pribyl",
        "ru_svodnyy_smetnyy_raschet",
        "ru_indeksy_i_uroven_cen",
        # Statutory context.
        "ru_gosekspertiza",
        "ru_nds_stroitelstvo",
    ],
    # The engine identifier behind the norm base above. It predates this pack
    # by a long way and is shared with the other countries that read the same
    # norm tradition (BY, KZ, UA, MN in the classification registry), which is
    # why the identifier is the method and not the country.
    validation_rule_sets=[
        "gesn",
    ],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    demo_template_ids=["residential-moscow", "school-stpetersburg"],
    branding=PartnerBranding(
        primary_color="#0039A6",  # blue of the national flag
        accent_color="#D52B1E",  # red of the national flag
        logo_path=None,  # no partner logo; the UI draws the country monogram
        favicon_path=None,
        powered_by_text=None,  # use the default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "RU",
        "country_name_en": "Russia",
        "country_name_ru": "Россия",
        "classification_standard": "gesn",
        "norm_base": "ФСНБ-2022",
        "norm_base_en": "Federal estimate norm base, 2022 edition",
        # A norm code is four fields: collection, section, table, norm. The
        # engine's ``gesn.valid_code`` compiles the same shape; the pattern is
        # published here so a reader and the rule cannot drift, and a test
        # compares the two rather than trusting either.
        "code_format": "CC-SS-TTT-NN",
        "code_example": "08-04-001-21",
        # The twelve chapters of the summary estimate calculation. The
        # platform already carries this list as the CBS dimension every
        # methodology seeds; this copy is what the onboarding wizard renders,
        # and the pack test asserts the two are the same twelve.
        "summary_estimate_chapters": [
            "1 Site preparation",
            "2 Main buildings and structures",
            "3 Auxiliary buildings and structures",
            "4 Energy facilities",
            "5 Transport and communications facilities",
            "6 External networks and utilities",
            "7 Site improvement and landscaping",
            "8 Temporary buildings and structures",
            "9 Other works and costs",
            "10 Maintenance of the developer / client",
            "11 Training of operating personnel",
            "12 Design and survey works",
        ],
        "regulator_refs": [
            "Приказ Минстроя России от 04.08.2020 № 421/пр (Методика определения сметной стоимости строительства)",
            "Приказ Минстроя России от 21.12.2020 № 812/пр (нормативы накладных расходов)",
            "Приказ Минстроя России от 11.12.2020 № 774/пр (нормативы сметной прибыли)",
            "ФГИС ЦС (Федеральная государственная информационная система ценообразования в строительстве)",
            "Градостроительный кодекс РФ, статья 8.3 (сметные нормативы и сметные цены)",
            "Постановление Правительства РФ от 05.03.2007 № 145 (проверка достоверности сметной стоимости)",
        ],
        "vat_standard_rate": 22,
        "currency_decimals": 2,
        "review_status": (
            "The norm code shape and the resource decomposition are derived "
            "from a published GESN base read in full (2604 norms, every code "
            "matching the shipped pattern). The markup structure follows the "
            "national stack the platform already carried. The statutory "
            "references are drawn from public sources and are pending review "
            "by a Russian cost engineer before they are relied on for a state "
            "contract."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
