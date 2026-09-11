"""Build the ``PartnerPackManifest`` instance for the spain-es pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="spain-es",
    partner_name="Spain Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Spanish contractors, arquitectos tecnicos and "
        "administraciones publicas: BC3/FIEBDC-3 exchange format, Codigo "
        "Tecnico de la Edificacion (CTE), Ley de Contratos del Sector "
        "Publico 9/2017, EHE-08 structural concrete, IVA at 21 percent, "
        "euro."
    ),
    default_locale="es",
    additional_locales={},
    cwicr_regions=[
        # One Spanish catalogue exists under this marketplace slug. It
        # resolves to ES_MADRID. Additional cities (Barcelona, Valencia,
        # Seville) are planned but no catalogue is published for them yet.
        "cwicr-es-madrid",
    ],
    default_currency="EUR",
    default_tax_template="es_iva_21",
    default_methodology="spain",
    validation_rule_packs=[],
    # No Spanish-specific engine rule set yet. When one is built it will
    # carry rules for BC3 item references and capitulo numbering.
    validation_rule_sets=[],
    default_modules=[],  # empty = show all
    hidden_modules=[],
    demo_template_ids=["mixed-use-barcelona"],
    branding=PartnerBranding(
        primary_color="#AA151B",  # Spanish red (flag)
        accent_color="#F1BF00",  # Spanish gold (flag)
        logo_path=None,  # no partner logo; the UI draws the country monogram
        favicon_path=None,
        powered_by_text=None,  # use the default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "ES",
        "country_name_en": "Spain",
        "country_name_es": "Espana",
        "classification_standard": "bc3",
        "regulator_refs": [
            "Ley de Contratos del Sector Publico (Ley 9/2017)",
            "Codigo Tecnico de la Edificacion (CTE, R.D. 314/2006)",
            "EHE-08 - Instruccion de Hormigon Estructural",
            "FIEBDC-3 / BC3 exchange format",
            "Ley de Ordenacion de la Edificacion (LOE, Ley 38/1999)",
            "Reglamento General de la Ley de Contratos (R.D. 1098/2001)",
        ],
        "vat_standard_rate": 21,
        "vat_reduced_rate": 10,
        "vat_super_reduced_rate": 4,
        "currency_decimals": 2,
        # Each autonomous community publishes its own base de precios.
        # The pack does not ship any of them; the onboarding wizard asks
        # which one the user works to.
        "autonomous_community_price_bases": [
            "Base de Precios de la Construccion de la Comunidad de Madrid",
            "ITEC (Institut de Tecnologia de la Construccio de Catalunya)",
            "PREOC (Base de Precios Centro, Guadalajara)",
            "Junta de Andalucia Base de Costes de la Construccion",
            "Gobierno Vasco - Base de Precios de Edificacion",
        ],
        "autonomous_community_note": (
            "Spain has 17 autonomous communities, each publishing its own "
            "base de precios. The onboarding wizard asks which one applies "
            "so the right reference is loaded. BC3/FIEBDC-3 is the common "
            "exchange format across all of them."
        ),
        "review_status": (
            "Regulatory references are drawn from public sources and are "
            "pending review by a Spanish aparejador or quantity surveyor "
            "before they are relied on for a public tender."
        ),
        "support_email": "info@datadrivenconstruction.io",
    },
)
