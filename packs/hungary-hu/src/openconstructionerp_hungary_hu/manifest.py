"""Build the ``PartnerPackManifest`` instance for the hungary-hu pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="hungary-hu",
    partner_name="Hungary Construction Pack",
    partner_url="https://www.bimcontrol.hu/",
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Hungarian contractors, designers and public "
        "clients: the seventeen-chapter building item order and the "
        "infrastructure item order with its per-project item numbers and "
        "code dictionaries, the material and fee split every Hungarian "
        "bill is quoted in, contingency and VAT on the summary sheet, "
        "public-procurement and site-diary references, forint at zero "
        "decimals."
    ),
    # English, deliberately. There is no Hungarian bundle among the UI
    # languages the application ships, and a pack cannot conjure one: a
    # default_locale the app has no strings for resolves back to English
    # anyway, so declaring "hu" here would promise a Hungarian interface and
    # deliver an English one with no signal that it had. The Hungarian
    # vocabulary this pack does carry lives where it is actually read: the
    # onboarding wizard's labels and the rule-pack documents. A Hungarian UI
    # bundle is a separate piece of work with its own quality bar.
    default_locale="en",
    additional_locales={},
    cwicr_regions=[],
    default_currency="HUF",
    # Documentation only, the way every other pack's tax template is: there
    # is no tax resolver behind this field yet. The rate itself lives in the
    # methodology template, which does drive the cascade.
    default_tax_template="hu_afa_27",
    default_methodology="hungary",
    validation_rule_packs=[
        # The two item orders, both read out of real Hungarian workbooks.
        "hu_magasepitesi_tetelrend",
        "hu_infrastruktura_tetelrend",
        # The shape of the money: material and fee, contingency, VAT.
        "hu_anyag_dij_bontas",
        # Statutory context.
        "hu_kozbeszerzes",
        "hu_kivitelezes_naplo",
        "hu_afa_epitoipar",
    ],
    # The engine identifier behind the two item orders above. Four rules run
    # under it: the item-code shape, the chapter, the material and fee split,
    # and the uniqueness of the per-project item number.
    validation_rule_sets=[
        "hungary",
    ],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    demo_template_ids=["residential-budapest", "office-debrecen"],
    branding=PartnerBranding(
        primary_color="#CE2939",  # red of the national flag
        accent_color="#477050",  # green of the national flag
        logo_path=None,  # no partner logo; the UI draws the country monogram
        favicon_path=None,
        powered_by_text="Developed in collaboration with Kocsis Tamás / BIM Control",
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "HU",
        "country_name_en": "Hungary",
        "country_name_hu": "Magyarország",
        "classification_standard": "tetelrend",
        "regulator_refs": [
            "2015. évi CXLIII. törvény a közbeszerzésekről (Public Procurement Act)",
            "322/2015. Korm. rendelet (procurement of construction works)",
            "191/2009. Korm. rendelet az építőipari kivitelezési tevékenységről",
            "e-építési napló (electronic construction log)",
            "2007. évi CXXVII. törvény az általános forgalmi adóról (VAT Act)",
        ],
        # The seventeen chapters of the building item order, in order. The
        # engine holds the same list; this copy is what the onboarding wizard
        # and the pack's own documentation render, and the test that keeps
        # them honest compares the two rather than trusting either.
        "building_chapters": [
            "01 ÁLTALÁNOS, JÁRULÉKOS KÖLTSÉGEK",
            "02 ELŐKÉSZÍTŐ MUNKÁK",
            "03 FÖLDMUNKA, ALAPOZÁS",
            "04 SZERKEZETÉPÍTÉSI MUNKÁK",
            "05 KÜLSŐ SZAKIPARI MUNKÁK, ÉPÜLET ZÁRÁS",
            "06 ÉPÍTÉSZETI, SZAKIPARI MUNKÁK",
            "07 BELSŐÉPÍTÉSZETI MUNKÁK",
            "08 MŰEMLÉKI, RESTAURÁTORI MUNKÁK",
            "09 ÉPÜLETGÉPÉSZET",
            "10 TŰZVÉDELMI RENDSZEREK, OLTÓRENDSZER",
            "11 ERŐSÁRAMÚ MUNKÁK",
            "12 GYENGEÁRAMÚ MUNKÁK",
            "13 AUTOMATIKA",
            "14 SPECIÁLIS TECHNOLÓGIA",
            "15 FELVONÓK, EMELŐSZERKEZETEK",
            "16 KÜLSŐ MUNKÁK",
            "17 ÁTADÁS",
        ],
        "vat_standard_rate": 27,
        "vat_reduced_rate": 5,
        "currency_decimals": 0,
        "collaboration": {
            "partner": "Kocsis Tamás",
            "organization": "BIM Control",
            "url": "https://www.bimcontrol.hu/",
            "role": "Domain expert for Hungarian construction standards and item orders",
        },
        "review_status": (
            "Item orders and the money structure are derived from Hungarian "
            "workbooks in production use. Developed in collaboration with "
            "Kocsis Tamás (BIM Control, bimcontrol.hu). The statutory "
            "references are drawn from public sources."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
