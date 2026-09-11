"""Build the ``PartnerPackManifest`` instance for the poland-pl pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="poland-pl",
    partner_name="Poland Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Polish contractors, designers and public "
        "clients: DIN 276 classification (Poland follows the German DIN "
        "tradition for cost grouping), PLN currency with 23% VAT, KNR "
        "and KNNR norm catalogues for labour and material norms, Prawo "
        "budowlane (Construction Law), Prawo zamowien publicznych (PZP) "
        "public procurement references, and the kosztorys inwestorski "
        "investor estimate format. Polish and English interface."
    ),
    default_locale="pl",
    additional_locales={},
    cwicr_regions=[
        "cwicr-pl-warsaw",  # resolves to PL_WARSAW
    ],
    default_currency="PLN",
    default_tax_template="pl_vat_23",
    default_methodology="poland",
    validation_rule_packs=[],
    # No Polish-specific engine rule set implemented yet.
    validation_rule_sets=[],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    demo_template_ids=["residential-warsaw"],
    branding=PartnerBranding(
        primary_color="#DC143C",  # Polish crimson (flag)
        accent_color="#FFFFFF",  # white (flag)
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "PL",
        "country_name_en": "Poland",
        "country_name_pl": "Polska",
        "classification_standard": "din276",
        "regulator_refs": [
            "Prawo zamowien publicznych (PZP, Public Procurement Law)",
            "Prawo budowlane (Construction Law)",
            "KNR (Katalog Nakladow Rzeczowych, catalogue of material norms)",
            "KNNR (Kosztorysowe Normy Nakladow Rzeczowych)",
            "Rozporzadzenie w sprawie kosztorysu inwestorskiego (investor estimate regulation)",
        ],
        "vat_standard_rate": 23,
        "vat_reduced_rate": 8,
        "review_status": (
            "Classification, currency and tax references are drawn from "
            "public sources. Regulatory references are pending review by "
            "a Polish quantity surveyor before they are relied on for a "
            "tender submission."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
