"""Build the ``PartnerPackManifest`` instance for the turkey-tr pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="turkey-tr",
    partner_name="Turkey Construction Pack",
    partner_url=None,
    pack_version="0.2.0",
    pack_type="country",
    description=(
        "Pre-configured for contractors, designers and clients in Türkiye: "
        "the poz numbering of the Ministry unit-price book for building, "
        "mechanical and electrical works, the units a Turkish bill is "
        "measured in, the combined 25 percent contractor profit and general "
        "expenses line, KDV at 20 percent with the two reduced rates, the "
        "public holiday calendar, Turkish lira at two decimals."
    ),
    default_locale="tr",
    # Empty on purpose: a file listed here is merged over the shipped Turkish
    # bundle for everyone on the installation, and the shipped bundle is the
    # one to improve.
    additional_locales={},
    cwicr_regions=[
        # Resolves to TR_NATIONAL, the base built from the official unit-price
        # lists, whose items carry poz numbers. That is the base a pack
        # classified by poz number has to load. "cwicr-tr-istanbul", declared
        # here until 0.2.0, is a different base (TR_ISTANBUL): a general
        # market catalogue with codes of its own and no poz numbers.
        "cwicr-tr-national",
    ],
    default_currency="TRY",
    # Documentation only, the way every other pack's tax template is: there
    # is no tax resolver behind this field. The rates themselves live in the
    # dated tax seed (TR rows for the 20 and the 10 percent; the 1 percent
    # tier is not seeded yet) and in the TR markup stack, which is what a new
    # bill charges KDV from.
    default_tax_template="tr_kdv_20",
    default_methodology="turkey",
    validation_rule_packs=[
        # The unit-price book: poz numbering, chapters, units, the 25 percent.
        "bayindirlik_unit_prices",
        # Mechanical and electrical installation references, the part of the
        # rule book an MEP contractor works to. Reference only, no engine rule.
        "tesisat_teknik_sartnameleri",
        # Statutory context for public and structural work. Reference only.
        "kamu_ihale",
        "tbdy_2018",
        "tse_standards",
    ],
    # The engine rule set that reads the poz number every Turkish line is
    # priced from. It shares its name with the classification key it reads,
    # unlike Hungary, where the classification is tetelrend and the rule set
    # is hungary, so the name is checked against the registry by test rather
    # than assumed.
    validation_rule_sets=["birimfiyat"],
    # Both empty on purpose. A country pack shows every module to every
    # Turkish user; a module preset belongs to an industry pack, not here.
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["mixed-use-istanbul"],
    branding=PartnerBranding(
        primary_color="#E30A17",  # Turkish red (flag background)
        accent_color="#FFFFFF",  # white (flag crescent and star)
        logo_path=None,  # no partner logo; the UI draws the country monogram
        favicon_path=None,
        powered_by_text=None,  # use the default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "TR",
        "country_name_en": "Türkiye",
        "country_name_tr": "Türkiye",
        "classification_standard": "birimfiyat",
        "regulator_refs": [
            "Çevre, Şehircilik ve İklim Değişikliği Bakanlığı, Yüksek Fen Kurulu Başkanlığı: "
            "İnşaat ve Tesisat Birim Fiyatları (annual unit prices and analyses)",
            "Yapım İşleri İhaleleri Uygulama Yönetmeliği, Madde 11 (25 percent contractor profit and general expenses)",
            "3065 sayılı Katma Değer Vergisi Kanunu and Karar 2007/13033 as amended by Karar 7346 (KDV rates)",
            "2429 sayılı Ulusal Bayram ve Genel Tatiller Hakkında Kanun (public holidays)",
            "Makina Tesisatı Genel Teknik Şartnamesi and Elektrik Tesisatı Genel Teknik Şartnamesi",
            "Binaların Yangından Korunması Hakkında Yönetmelik (2007/12937)",
            "4734 sayılı Kamu İhale Kanunu and 4735 sayılı Kamu İhale Sözleşmeleri Kanunu",
            "4708 sayılı Yapı Denetimi Hakkında Kanun",
            "Türkiye Bina Deprem Yönetmeliği 2018 (TBDY)",
        ],
        # The chapters of the Ministry unit-price book, by the first group of
        # the poz number. The engine holds the same table; this copy is what
        # the pack's own documentation renders, and the test that keeps them
        # honest compares the two rather than trusting either.
        "poz_chapters": [
            "10 Rayiçler",
            "15 İnşaat",
            "19 Makine saatlik ücret analizleri",
            "25 Mekanik tesisat",
            "35 Elektrik tesisatı",
        ],
        # Decree 7346 (Resmî Gazete 7 July 2023, no. 32241) raised the general
        # rate from 18 to 20 and the list (II) rate from 8 to 10 with effect
        # from 10 July 2023; the list (I) rate stayed at 1.
        # https://www.resmigazete.gov.tr/eskiler/2023/07/20230707-11.pdf
        "vat_standard_rate": 20,
        "vat_reduced_rate": 10,
        "vat_rates": [20, 10, 1],
        "contractor_profit_and_overhead_percent": 25,
        "currency_decimals": 2,
        "review_status": (
            "Drawn from the published legislation and from the structure of "
            "the Ministry unit-price book. Pending review by a Turkish "
            "quantity surveyor and a Turkish accountant: do not rely on it "
            "for a tender or a tax filing before that review."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
