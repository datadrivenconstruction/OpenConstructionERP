"""Build the ``PartnerPackManifest`` instance for the portugal-pt pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="portugal-pt",
    partner_name="Portugal Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for the Portuguese construction market: EUR "
        "currency with 23% IVA, ProNIC classification references, "
        "Portuguese orcamento (budget) estimating practice."
    ),
    default_locale="pt",
    additional_locales={},
    cwicr_regions=[],
    default_currency="EUR",
    default_tax_template="pt_iva_23",
    default_methodology="portugal",
    validation_rule_packs=[],
    validation_rule_sets=[
        "masterformat",
    ],
    default_modules=[],
    hidden_modules=[],
    demo_template_ids=["office-lisbon", "residential-porto"],
    branding=PartnerBranding(
        primary_color="#006600",  # green of the Portuguese flag
        accent_color="#FF0000",  # red of the Portuguese flag
        logo_path=None,
        favicon_path=None,
        powered_by_text=None,
    ),
    onboarding_script_path=None,
    metadata={
        "country": "PT",
        "country_name_en": "Portugal",
        "country_name_pt": "Portugal",
        "classification_standard": "masterformat",
        "measurement_system": "metric",
        "regulator_refs": [
            "ProNIC (Protocolo para a Normalizacao da Informacao Tecnica na Construcao)",
            "Codigo dos Contratos Publicos (Public Contracts Code, DL 18/2008)",
            "RGEU (Regulamento Geral das Edificacoes Urbanas)",
            "RCCTE/SCE (Regulamento das Caracteristicas de Comportamento Termico, energy)",
            "NP EN Eurocodes (Portuguese adoption of European structural standards)",
            "LNEC (Laboratorio Nacional de Engenharia Civil, technical specifications)",
        ],
        "vat_standard_rate": 23,
        "vat_reduced_rate": 6,
        "support_email": "info@datadrivenconstruction.io",
    },
)
