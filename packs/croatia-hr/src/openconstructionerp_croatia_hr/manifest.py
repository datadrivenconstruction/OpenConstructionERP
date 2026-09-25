"""Build the ``PartnerPackManifest`` instance for the croatia-hr pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="croatia-hr",
    partner_name="Croatia Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Croatian contractors, designers and public "
        "clients: the troškovnik (priced bill of quantities) with all-in "
        "unit rates grouped into construction, finishing trade and "
        "installation works, EUR currency with PDV at 25% and the 13%, 5% "
        "and 0% rates on file, Zakon o gradnji (Building Act) and Zakon o "
        "javnoj nabavi (Public Procurement Act) references, and DIN 276 as "
        "the nearest cost hierarchy the platform supports. Croatian and "
        "English interface."
    ),
    # The UI ships a Croatian bundle, so the interface really is Croatian.
    default_locale="hr",
    additional_locales={},
    cwicr_regions=[
        "cwicr-hr-zagreb",  # resolves to HR_ZAGREB, priced in EUR
    ],
    # Croatia replaced the kuna with the euro on 2023-01-01.
    default_currency="EUR",
    # Documentation only, the way every other pack's tax template is. The
    # rates themselves live in the platform's dated tax table
    # (oe_i18n_tax_config): PDV 25 % since 2012-03-01 as the default, 13 %
    # since 2014-01-01, 5 % since 2013-01-01 and 0 % on solar panel
    # installation since 2022-10-01.
    default_tax_template="hr_pdv_25",
    # No Croatian methodology template yet. A troškovnik carries overheads
    # and profit inside every unit rate rather than as separate lines, so a
    # template with invented overhead and profit percentages would describe
    # a method Croatian estimators do not use.
    default_methodology=None,
    validation_rule_packs=[
        "hr_troskovnik",
        "hr_zakon_o_gradnji",
        "hr_javna_nabava",
        "hr_pdv",
        "hr_fiskalizacija_eracun",
    ],
    # DIN 276 is the nearest supported hierarchy for a Croatian bill, the
    # same choice the Czech and Polish packs make for their national bills.
    validation_rule_sets=[
        "din276",
    ],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    demo_template_ids=["residential-zagreb", "office-split"],
    branding=PartnerBranding(
        primary_color="#171796",  # blue of the national flag
        accent_color="#FF0000",  # red of the national flag
        logo_path=None,  # no partner logo; the UI draws the country monogram
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "HR",
        "country_name_en": "Croatia",
        "country_name_hr": "Hrvatska",
        "classification_standard": "din276",
        "regulator_refs": [
            "Zakon o gradnji (NN 153/13, 20/17, 39/19, 125/19), Building Act",
            "Zakon o prostornom uređenju (NN 153/13 and amendments), Physical Planning Act",
            "Zakon o javnoj nabavi (NN 120/16, 114/22), Public Procurement Act",
            "Zakon o porezu na dodanu vrijednost (NN 73/13 and amendments), VAT Act",
            "Zakon o fiskalizaciji (NN 89/25), e-Račun under EN 16931 from 2026-01-01",
            "Pravilnik o građevnom dnevniku, construction log",
            "HRN EN Eurocodes (Croatian adoption of the European structural standards)",
        ],
        # The chapter order a Croatian troškovnik follows. Every chapter
        # carries all-in unit rates and closes with a chapter total, and the
        # recapitulation adds PDV once, on the sum of the chapters.
        "troskovnik_chapters": [
            "Pripremni radovi (Preliminary works)",
            "Zemljani radovi (Earthworks)",
            "Betonski i armiranobetonski radovi (Concrete and reinforced concrete works)",
            "Zidarski radovi (Masonry works)",
            "Izolaterski radovi (Insulation and waterproofing)",
            "Krovopokrivački i limarski radovi (Roofing and sheet metal works)",
            "Stolarski i bravarski radovi (Joinery and metalwork)",
            "Keramičarski i podopolagački radovi (Tiling and floor finishes)",
            "Soboslikarski i ličilački radovi (Painting and decorating)",
            "Fasaderski radovi (Façade works)",
            "Instalacije (Mechanical, electrical and plumbing installations)",
            "Vanjsko uređenje (External works)",
        ],
        "vat_standard_rate": 25,
        "vat_reduced_rate": 13,
        "vat_rates": [25, 13, 5, 0],
        "review_status": (
            "Currency, tax rates and regulatory references are drawn from "
            "public sources. The troškovnik chapter order reflects common "
            "Croatian practice and is pending review by a Croatian cost "
            "engineer (ovlašteni inženjer) before it is relied on for a "
            "public tender."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
