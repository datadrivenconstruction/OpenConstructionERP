"""Regional configuration for Latin America."""

from typing import Any

PACK_CONFIG: dict[str, Any] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    "region_code": "LATAM",
    "countries": ["BR", "MX", "AR", "CL", "CO", "PE"],
    "default_currency": "BRL",
    "supported_currencies": ["BRL", "MXN", "ARS", "CLP", "COP", "PEN", "USD"],
    "default_locale": "pt-BR",
    "measurement_system": "metric",
    "paper_size": "A4",
    "date_format": "DD/MM/YYYY",
    "number_format": "1.234,56",
    # ── Standards — Brazil ───────────────────────────────────────────────────
    "standards": [
        {
            "code": "SINAPI",
            "name": "SINAPI — Sistema Nacional de Pesquisa de Custos e Índices",
            "country": "BR",
            "description": (
                "National system of construction cost research and indices, "
                "maintained by IBGE and Caixa Econômica Federal; "
                "mandatory reference for federal public works"
            ),
            "components": [
                {"code": "SINAPI_COMP", "title": "Composições (cost compositions)"},
                {"code": "SINAPI_INS", "title": "Insumos (input prices by state)"},
                {"code": "SINAPI_REF", "title": "Curva ABC (cost curve analysis)"},
            ],
        },
        {
            "code": "TCPO",
            "name": "TCPO — Tabelas de Composições de Preços para Orçamentos",
            "country": "BR",
            "description": "PINI cost composition tables for private-sector estimating",
        },
        {
            "code": "NBR",
            "name": "ABNT NBR Standards",
            "country": "BR",
            "description": "Brazilian technical standards issued by ABNT",
            "key_codes": [
                {"code": "NBR 12721", "title": "Avaliação de custos unitários de construção"},
                {"code": "NBR 6118", "title": "Projeto de estruturas de concreto"},
                {"code": "NBR 8800", "title": "Projeto de estruturas de aço"},
                {"code": "NBR 15575", "title": "Desempenho de edificações habitacionais"},
            ],
        },
        # ── Standards — Mexico ───────────────────────────────────────────────
        {
            "code": "NTDIF",
            "name": "NTDIF — Normas Técnicas de Diseño e Instalación de Facilidades",
            "country": "MX",
            "description": "Technical standards for facility design and installation",
        },
        {
            "code": "NMX",
            "name": "NMX — Normas Mexicanas",
            "country": "MX",
            "description": "Mexican voluntary technical standards for construction",
        },
        {
            "code": "BIMSA",
            "name": "BIMSA Reports — Cost Data Mexico",
            "country": "MX",
            "description": "Construction cost indices and data for Mexico",
        },
        # ── Standards — Argentina ────────────────────────────────────────────
        {
            "code": "IRAM",
            "name": "IRAM — Instituto Argentino de Normalización y Certificación",
            "country": "AR",
            "description": "Argentine standards body for construction and engineering",
        },
        {
            "code": "CAC",
            "name": "CAC — Cámara Argentina de la Construcción",
            "country": "AR",
            "description": "Argentine construction chamber cost indices",
        },
        # ── Standards — Chile ────────────────────────────────────────────────
        {
            "code": "NCH",
            "name": "NCh — Normas Chilenas",
            "country": "CL",
            "description": "Chilean national standards for construction",
        },
    ],
    # ── Contract types ───────────────────────────────────────────────────────
    "contract_types": [
        {
            "code": "BR_EMPREITADA_GLOBAL",
            "name": "Empreitada por Preço Global",
            "country": "BR",
            "description": "Lump-sum construction contract (Brazil)",
        },
        {
            "code": "BR_EMPREITADA_UNITARIO",
            "name": "Empreitada por Preço Unitário",
            "country": "BR",
            "description": "Unit-price construction contract (Brazil)",
        },
        {
            "code": "BR_TAREFA",
            "name": "Contrato por Tarefa",
            "country": "BR",
            "description": "Task-based contract for smaller works (Brazil)",
        },
        {
            "code": "MX_PRECIO_UNITARIO",
            "name": "Contrato a Precio Unitario",
            "country": "MX",
            "description": "Unit-price contract (Mexico)",
        },
        {
            "code": "MX_PRECIO_ALZADO",
            "name": "Contrato a Precio Alzado",
            "country": "MX",
            "description": "Lump-sum (fixed price) contract (Mexico)",
        },
        {
            "code": "MX_MIXTO",
            "name": "Contrato Mixto",
            "country": "MX",
            "description": "Mixed contract combining unit-price and lump-sum (Mexico)",
        },
        {
            "code": "AR_AJUSTE_ALZADO",
            "name": "Contrato de Ajuste Alzado",
            "country": "AR",
            "description": "Fixed-price contract (Argentina)",
        },
        {
            "code": "AR_UNIDAD_MEDIDA",
            "name": "Contrato por Unidad de Medida",
            "country": "AR",
            "description": "Unit-price contract (Argentina)",
        },
    ],
    # ── Tax rules ────────────────────────────────────────────────────────────
    "tax_rules": [
        {
            "code": "BR_ISS",
            "name": "ISS — Imposto Sobre Serviços",
            "type": "service_tax",
            "country": "BR",
            "rate_pct": "2–5",
            "description": "Municipal service tax on construction services (varies by municipality)",
        },
        {
            "code": "BR_PIS_COFINS",
            "name": "PIS/COFINS — Federal Contributions",
            "type": "federal_contribution",
            "country": "BR",
            "rate_pct": "3.65",
            "description": "Combined PIS (0.65%) + COFINS (3%) for cumulative regime",
            "note": "Non-cumulative regime: PIS 1.65% + COFINS 7.6% = 9.25%",
        },
        {
            "code": "BR_ICMS",
            "name": "ICMS — State VAT on Materials",
            "type": "state_vat",
            "country": "BR",
            "rate_pct": "7–18",
            "description": "State circulation tax on goods (rate varies by state and product)",
        },
        {
            "code": "MX_IVA",
            "name": "IVA — Impuesto al Valor Agregado",
            "type": "vat",
            "country": "MX",
            "rate_pct": "16",
            "description": "Mexico value-added tax (standard rate)",
        },
        {
            "code": "MX_IVA_FRONTERA",
            "name": "IVA — Border Zone Rate",
            "type": "vat",
            "country": "MX",
            "rate_pct": "8",
            "description": "Reduced IVA for northern border zone stimulus",
        },
        {
            "code": "AR_IVA",
            "name": "IVA — Impuesto al Valor Agregado",
            "type": "vat",
            "country": "AR",
            "rate_pct": "21",
            "description": "Argentina value-added tax (standard rate)",
        },
        {
            "code": "AR_IVA_REDUCED",
            "name": "IVA — Reduced Rate",
            "type": "vat",
            "country": "AR",
            "rate_pct": "10.5",
            "description": "Reduced IVA for construction works",
        },
        {
            "code": "CL_IVA",
            "name": "IVA — Impuesto al Valor Agregado",
            "type": "vat",
            "country": "CL",
            "rate_pct": "19",
            "description": "Chile value-added tax",
        },
        {
            "code": "CO_IVA",
            "name": "IVA — Impuesto al Valor Agregado",
            "type": "vat",
            "country": "CO",
            "rate_pct": "19",
            "description": "Colombia value-added tax",
        },
        {
            "code": "PE_IGV",
            "name": "IGV — Impuesto General a las Ventas",
            "type": "vat",
            "country": "PE",
            "rate_pct": "18",
            "description": "Peru general sales tax (IGV 16% + IPM 2%)",
        },
    ],
    # ── Brazil BDI reference ─────────────────────────────────────────────────
    "brazil_bdi": {
        "name": "BDI — Bonificações e Despesas Indiretas",
        "description": (
            "Overhead and profit markup applied to direct costs in Brazilian public works. "
            "TCU Acordão 2622/2013 reference ranges."
        ),
        "reference_ranges": {
            "buildings": {"min_pct": "20.34", "max_pct": "25.00", "typical_pct": "22.12"},
            "road_works": {"min_pct": "16.80", "max_pct": "22.20", "typical_pct": "18.34"},
            "supply_only": {"min_pct": "11.10", "max_pct": "16.80", "typical_pct": "14.02"},
        },
    },
    # ── Units (metric defaults) ──────────────────────────────────────────────
    "default_units": {
        "length": "m",
        "area": "m²",
        "volume": "m³",
        "weight": "kg",
        "temperature": "°C",
    },
}
