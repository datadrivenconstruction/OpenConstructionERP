"""Build the ``PartnerPackManifest`` instance for the brazil-sinapi pack.

Kept in its own module so unit tests can import the manifest without
triggering the package ``__init__`` side-effects.

Standards bundled (verified 2026-05-28):
  * SINAPI — Sistema Nacional de Pesquisas de Custos e Indices (Caixa
    Economica Federal + IBGE). Monthly mes-ref publication. The cost
    rule pack validates BDI bands per TCU 2622/2013, encargos sociais
    (desonerados vs nao-desonerados), composicao/insumo distinction
    and the 7-digit code format.
  * NBR 12721:2006 (+ Errata 1:2007) — Avaliacao de custos unitarios
    de construcao para incorporacao imobiliaria (CUB).
  * NBR 6118:2023 — Projeto de estruturas de concreto.
  * NBR 8800:2008 — Projeto de estruturas de aco.
  * NBR 9050:2020 — Acessibilidade (MANDATORY for public/commercial
    buildings, federal Lei 10.098/2000 + Decreto 5.296/2004).
  * NBR 5419:2015 (parts 1-4) — Protecao contra descargas atmosfericas.
  * Lei nº 14.133/2021 — Nova Lei de Licitacoes e Contratos
    Administrativos (replaced Lei 8.666/1993 since 2023-12-30).
  * RPS / NFS-e — Recibo Provisorio de Servicos (municipal).

Tax model:
  * br_iss_municipal (ISS is collected by the municipio, not the
    estado — alíquota 2-5%). The slug was previously br_iss_state;
    that was incorrect Brazilian tax topology. Federal complements
    (PIS / COFINS / IRPJ / CSLL) and the state ICMS on materials are
    handled by the finance module's standard tax-line templates.

CWICR regions:
  * Only ``cwicr-pt-saopaulo`` is published in the marketplace today
    (see ``backend/app/core/marketplace.py``). Additional Brazilian
    metros (RJ / Brasilia-DF / Belo Horizonte / Salvador) are listed
    in ``metadata.preferred_metros`` so the onboarding wizard can
    pre-fill the dropdown when those marketplace entries land.
"""

from __future__ import annotations

from app.core.partner_pack.manifest import PartnerBranding, PartnerPackManifest

MANIFEST = PartnerPackManifest(
    slug="brazil-sinapi",
    partner_name="Brazil Construction Pack",
    partner_url=None,
    pack_version="0.2.0",
    description=(
        "Pre-configured for Brazilian construction firms: SINAPI cost "
        "database, NBR 12721 CUB, ABNT structural codes (NBR 6118 / 8800), "
        "NBR 9050 accessibility, NBR 5419 lightning protection, Lei 14.133/2021 "
        "public procurement, RPS/NFS-e PDF generation, municipal ISS taxation."
    ),
    default_locale="pt",
    additional_locales={
        "pt": "locales/pt-BR.json",
    },
    cwicr_regions=[
        # Only one Brazilian CWICR region is published in the marketplace
        # today (see backend/app/core/marketplace.py). Additional metros
        # are recorded in metadata.preferred_metros for the onboarding UI.
        "cwicr-pt-saopaulo",
    ],
    default_currency="BRL",
    default_tax_template="br_iss_municipal",
    validation_rule_packs=[
        "sinapi_cost_db",
        "nbr_12721",
        "abnt_concrete",
        "abnt_steel",
        "nbr_9050_2020",
        "nbr_5419_2015",
        "lei_14133_2021",
        "rps_pdf_generation",
    ],
    default_modules=[],   # empty = show all
    hidden_modules=[],
    demo_template_ids=["residential-saopaulo"],
    branding=PartnerBranding(
        primary_color="#009C3B",   # Brazil green (flag)
        accent_color="#FFDF00",    # Brazil yellow (flag)
        logo_path="logo.svg",
        favicon_path=None,
        powered_by_text=None,      # use default co-branding string
    ),
    onboarding_script_path="onboarding.yaml",
    metadata={
        "country": "BR",
        "country_name_en": "Brazil",
        "country_name_pt": "Brasil",
        "regulator_refs": [
            "SINAPI",
            "NBR 12721:2006",
            "NBR 6118:2023",
            "NBR 8800:2008",
            "NBR 9050:2020",
            "NBR 5419:2015",
            "Lei 14.133/2021",
            "RPS / NFS-e",
            "ISS municipal",
        ],
        "support_email": "info@datadrivenconstruction.io",
        # Pre-defined city presets surfaced in the onboarding wizard.
        # The corresponding CWICR regional cost databases will arrive
        # in marketplace updates; for now only Sao Paulo is wired in.
        "preferred_metros": [
            {"city": "Sao Paulo", "uf": "SP", "cwicr_slug": "cwicr-pt-saopaulo"},
            {"city": "Rio de Janeiro", "uf": "RJ", "cwicr_slug": None},
            {"city": "Brasilia", "uf": "DF", "cwicr_slug": None},
            {"city": "Belo Horizonte", "uf": "MG", "cwicr_slug": None},
            {"city": "Salvador", "uf": "BA", "cwicr_slug": None},
        ],
        # ISS is collected per municipio (range 2%-5%, fixed by federal
        # LC 116/2003). Surfaced for the onboarding wizard to drive
        # the default RPS aliquota.
        "iss_aliquota_range": {"min": 2.0, "max": 5.0, "typical": 3.0},
        # BDI ceiling per Acordao TCU 2622/2013 (public works).
        "bdi_band_tcu_2622_2013": {
            "buildings": {"min": 20.34, "typical": 24.18, "max": 27.07},
            "infrastructure": {"min": 20.21, "typical": 24.23, "max": 27.86},
        },
    },
)
