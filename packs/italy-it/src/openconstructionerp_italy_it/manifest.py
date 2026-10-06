"""Build the ``PartnerPackManifest`` instance for the italy-it pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="italy-it",
    partner_name="Italy Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Italian contractors, studi tecnici and "
        "stazioni appaltanti: prezzari regionali DEI methodology, Codice "
        "dei contratti pubblici (D.Lgs. 36/2023), NTC 2018 structural "
        "code, UNI construction standards, IVA at 22 percent, euro."
    ),
    default_locale="it",
    additional_locales={},
    cwicr_regions=[
        # The Rome catalogue, and the base built from the Prezzario dei
        # Lavori Pubblici della Toscana (IT_TOSCANA, 2026 edition, CC BY 4.0,
        # credited to Regione Toscana wherever it is offered). Other
        # regions' lists are imported by the user from the files the
        # region publishes (Cost databases, Import a regional price list).
        "cwicr-it-rome",
        "cwicr-it-toscana",
    ],
    default_currency="EUR",
    default_tax_template="it_iva_22",
    default_methodology="italy",
    validation_rule_packs=[
        "dlgs_36_2023",
        "prezzario_regionale",
        "uni_standards",
        "ntc_2018",
    ],
    validation_rule_sets=["italy"],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    demo_template_ids=["residential-rome"],
    branding=PartnerBranding(
        primary_color="#009246",  # Italian green (flag)
        accent_color="#CE2B37",  # Italian red (flag)
        logo_path=None,  # no partner logo; the UI draws the country monogram
        favicon_path=None,
        powered_by_text=None,  # use the default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "IT",
        "country_name_en": "Italy",
        "country_name_it": "Italia",
        "classification_standard": "voci",
        "regulator_refs": [
            "Codice dei contratti pubblici (D.Lgs. 36/2023)",
            "Prezzari regionali DEI (regional price lists)",
            "NTC 2018 - Norme Tecniche per le Costruzioni (D.M. 17/01/2018)",
            "UNI standards (construction and building materials)",
            "Testo Unico Edilizia (D.P.R. 380/2001)",
            "Codice Civile artt. 1655-1677 (appalto)",
        ],
        "vat_standard_rate": 22,
        "vat_reduced_rate": 10,
        "vat_super_reduced_rate": 4,
        "currency_decimals": 2,
        "review_status": (
            "Regulatory references are drawn from public sources and are "
            "pending review by an Italian geometra or quantity surveyor "
            "before they are relied on for a public tender."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
