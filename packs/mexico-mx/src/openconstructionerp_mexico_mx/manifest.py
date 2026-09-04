"""Build the ``PartnerPackManifest`` instance for the Mexico pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.

This pack pre-configures OpenConstructionERP for Mexican construction. It is
built entirely from public Mexican standards, laws and tax rules: the APU
unit-price method under the LOPSRM public-works law and its reglamento, IVA
with the border-region rate and IVA/ISR retenciones, CFDI 4.0 invoicing, the
social-housing bodies and site-safety norms.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="mexico-mx",
    partner_name="Mexico Construction Pack",
    partner_url=None,
    pack_version="0.1.0",
    pack_type="country",
    description=(
        "Pre-configured for Mexican construction: the APU unit-price method "
        "(materiales, mano de obra, maquinaria, indirectos, financiamiento, "
        "utilidad and cargos adicionales) under the LOPSRM public-works law, "
        "IVA 16 percent with the 8 percent border region and IVA/ISR "
        "retenciones, CFDI 4.0 invoicing fields, social-housing bodies "
        "(INFONAVIT, FOVISSSTE, CONAVI), IMSS and NOM-031-STPS site safety, "
        "32 states, and MXN."
    ),
    # Mexican Spanish, not Spanish. The platform registers and offers es-MX as
    # its own UI language, and this pack ships an es-MX overlay of its own, so
    # declaring the bare "es" booted a Mexican workspace into Iberian Spanish
    # with es-MX sitting unused beside it - costo read as coste, cimbra as
    # encofrado, estimacion de obra as certificacion de obra. The frontend
    # resolver (matchSupportedLanguage in frontend/src/app/i18n.ts) already
    # prefers a region subtag whenever one is offered; it was never given one
    # to prefer, because the onboarding wizard activates this field verbatim.
    default_locale="es-MX",
    additional_locales={
        "es-MX": "locales/es-MX.json",
    },
    # MX_MEXICO is the canonical CWICR region for Mexico (currency MXN). The
    # marketplace slug below resolves to it through the city-token index (token
    # "mexico"); the HuggingFace snapshot is published under the legacy stem
    # MX_MEXICOCITY and resolved automatically by the cost layer.
    cwicr_regions=[
        "cwicr-es-mexico",
    ],
    default_currency="MXN",
    default_tax_template="mx_iva_16",
    default_methodology="mexico",
    # Built-in engine rule sets: the Mexican rules plus universal BOQ quality.
    # These are what actually run; a project created under this pack inherits
    # them.
    validation_rule_sets=[
        "mexico",
        "boq_quality",
    ],
    validation_rule_packs=[
        # Documentation rule packs shipped with this pack (reference context for
        # the Mexican standards; not executed by the engine).
        "apu_precios_unitarios",
        "iva_retenciones_cfdi",
        "lopsrm_obra_publica",
        "vivienda_social_infonavit",
        "imss_nom_seguridad",
    ],
    # Empty = show all modules (Shape A, no module hiding). The Mexican module
    # oe_mexico_pack ships enabled in its own manifest, so it is active without
    # being listed here; listing modules here would hide every other module.
    default_modules=[],
    hidden_modules=[],
    # The pack ships two Mexican demo projects (a Ciudad de Mexico mixed-use
    # tower flagship and a Monterrey residential complex). An empty list keeps
    # the default flagship plus country-fill behaviour, which lands both MX
    # projects, rather than pinning them explicitly here.
    demo_template_ids=[],
    branding=PartnerBranding(
        primary_color="#006847",  # Mexican flag green
        accent_color="#CE1126",  # Mexican flag red
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,  # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "MX",
        "country_name_en": "Mexico",
        "country_name_es": "Mexico",
        "iso_3166_1_alpha_2": "MX",
        "vat_name": "IVA",
        "vat_standard_rate_pct": 16.0,
        "vat_border_region_rate_pct": 8.0,
        "vat_zero_rate_pct": 0.0,
        "measurement_system": "metric",
        "paper_size": "Letter",
        "official_language": "Spanish (es)",
        "estimating_method": "APU - analisis de precios unitarios",
        "states_count": 32,
        "regulator_refs": [
            "Ley de Obras Publicas y Servicios Relacionados con las Mismas (LOPSRM)",
            "Reglamento de la LOPSRM (integration of precios unitarios)",
            "Ley del Impuesto al Valor Agregado (SAT, IVA 16 percent, 8 percent border region)",
            "CFDI 4.0 electronic invoicing (SAT): RFC, regimen fiscal, uso CFDI",
            "Instituto Mexicano del Seguro Social (IMSS) employer obligations",
            "NOM-031-STPS-2011 construction site safety (STPS)",
            "INFONAVIT, FOVISSSTE and CONAVI social-housing finance and policy",
        ],
        "contract_suite": [
            "Contrato a precios unitarios",
            "Contrato a precio alzado",
            "Contrato mixto",
        ],
        "default_contract": "Contrato a precios unitarios",
        "social_housing_bodies": ["INFONAVIT", "FOVISSSTE", "CONAVI"],
        "pilot_project_types": [
            "social housing (vivienda social)",
            "private residential (vivienda residencial)",
        ],
        "support_email": "info@datadrivenconstruction.io",
    },
)
