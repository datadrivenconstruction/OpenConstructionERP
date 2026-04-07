"""Regional configuration for Russia and CIS countries."""

from typing import Any

PACK_CONFIG: dict[str, Any] = {
    # ── Identity ─────────────────────────────────────────────────────────────
    "region_code": "RU",
    "countries": ["RU", "BY", "KZ", "UZ", "KG"],
    "default_currency": "RUB",
    "default_locale": "ru",
    "measurement_system": "metric",
    "paper_size": "A4",
    "date_format": "DD.MM.YYYY",
    "number_format": "1 234,56",
    # ── Standards ────────────────────────────────────────────────────────────
    "standards": [
        {
            "code": "GESN",
            "name": "ГЭСН — Государственные элементные сметные нормы",
            "name_en": "GESN — State Elemental Estimate Norms",
            "description": "Federal elemental cost norms for construction works",
            "editions": ["GESN-2001", "GESN-2020", "GESN-2024"],
            "sections": [
                {"number": "01", "title": "Земляные работы"},
                {"number": "06", "title": "Бетонные и железобетонные конструкции монолитные"},
                {"number": "07", "title": "Бетонные и железобетонные конструкции сборные"},
                {"number": "08", "title": "Конструкции из кирпича и блоков"},
                {"number": "09", "title": "Строительные металлические конструкции"},
                {"number": "10", "title": "Деревянные конструкции"},
                {"number": "11", "title": "Полы"},
                {"number": "12", "title": "Кровли"},
                {"number": "15", "title": "Отделочные работы"},
                {"number": "16", "title": "Трубопроводы внутренние"},
                {"number": "17", "title": "Водопровод и канализация"},
                {"number": "18", "title": "Отопление"},
                {"number": "19", "title": "Газоснабжение"},
                {"number": "20", "title": "Вентиляция и кондиционирование"},
                {"number": "21", "title": "Электротехнические устройства"},
            ],
        },
        {
            "code": "FER",
            "name": "ФЕР — Федеральные единичные расценки",
            "name_en": "FER — Federal Unit Rates",
            "description": "Federal unit rates derived from GESN (base prices)",
        },
        {
            "code": "TER",
            "name": "ТЕР — Территориальные единичные расценки",
            "name_en": "TER — Territorial Unit Rates",
            "description": "Regional unit rates with territorial coefficients",
        },
        {
            "code": "SP",
            "name": "СП — Своды правил (Building Codes)",
            "name_en": "SP — Codes of Practice",
            "description": "Russian construction codes of practice",
        },
    ],
    # ── Cost estimation methods ──────────────────────────────────────────────
    "estimation_methods": [
        {
            "code": "RESOURCE",
            "name": "Ресурсный метод",
            "name_en": "Resource method",
            "description": "Cost estimation based on actual resource prices",
        },
        {
            "code": "BASE_INDEX",
            "name": "Базисно-индексный метод",
            "name_en": "Base-index method",
            "description": "Base prices adjusted by regional and temporal indices",
        },
        {
            "code": "RESOURCE_INDEX",
            "name": "Ресурсно-индексный метод",
            "name_en": "Resource-index method",
            "description": "Hybrid of resource and index methods",
        },
    ],
    # ── Contract types ───────────────────────────────────────────────────────
    "contract_types": [
        {
            "code": "DOGOVOR_PODRYADA",
            "name": "Договор строительного подряда (ГК РФ гл. 37 § 3)",
            "name_en": "Construction Contract (Civil Code ch. 37 § 3)",
            "description": "Standard construction contract under Russian Civil Code",
        },
        {
            "code": "DOGOVOR_GENPODRIAD",
            "name": "Договор генерального подряда",
            "name_en": "General Contractor Agreement",
            "description": "General contractor agreement with subcontracting rights",
        },
        {
            "code": "GOSUDARSTVENNY_KONTRAKT",
            "name": "Государственный контракт (44-ФЗ / 223-ФЗ)",
            "name_en": "Government Contract (Federal Law 44/223)",
            "description": "Public procurement contract under federal procurement law",
        },
    ],
    # ── Tax rules ────────────────────────────────────────────────────────────
    "tax_rules": [
        {
            "code": "RU_NDS_STANDARD",
            "name": "НДС — Стандартная ставка",
            "name_en": "VAT — Standard Rate",
            "type": "vat",
            "rate_pct": "20",
        },
        {
            "code": "RU_NDS_REDUCED",
            "name": "НДС — Пониженная ставка",
            "name_en": "VAT — Reduced Rate",
            "type": "vat",
            "rate_pct": "10",
            "note": "Applies to certain food, children's goods, medical supplies",
        },
        {
            "code": "RU_NDS_ZERO",
            "name": "НДС — Нулевая ставка",
            "name_en": "VAT — Zero Rate",
            "type": "vat",
            "rate_pct": "0",
            "note": "Export and certain international services",
        },
    ],
    # ── Payment and acceptance forms ─────────────────────────────────────────
    "payment_templates": [
        {
            "code": "KS_2",
            "name": "Акт о приёмке выполненных работ (форма КС-2)",
            "name_en": "Act of Acceptance of Completed Works (KS-2)",
            "description": (
                "Itemised acceptance act listing completed work items, "
                "quantities, and amounts for a reporting period"
            ),
            "fields": [
                "act_number",
                "reporting_period",
                "contract_number",
                "contractor_name",
                "object_name",
                "work_items",
                "total_amount",
                "signatures",
            ],
        },
        {
            "code": "KS_3",
            "name": "Справка о стоимости выполненных работ (форма КС-3)",
            "name_en": "Certificate of Cost of Completed Works (KS-3)",
            "description": (
                "Summary certificate of total cost for the period, "
                "cumulative total, and payment schedule"
            ),
            "fields": [
                "certificate_number",
                "reporting_period",
                "contract_sum",
                "completed_from_start",
                "completed_this_period",
                "nds_amount",
                "total_with_nds",
            ],
        },
        {
            "code": "KS_6A",
            "name": "Журнал учёта выполненных работ (форма КС-6а)",
            "name_en": "Work Execution Journal (KS-6a)",
            "description": "Cumulative log of all work performed on the object",
        },
    ],
    # ── Regional indices source ──────────────────────────────────────────────
    "index_sources": [
        {
            "code": "MINSTROI",
            "name": "Минстрой России — индексы пересчёта",
            "name_en": "Ministry of Construction — recalculation indices",
            "description": "Quarterly price indices published by the Ministry of Construction",
            "url": "https://minstroyrf.gov.ru",
        },
    ],
    # ── Units (metric defaults) ──────────────────────────────────────────────
    "default_units": {
        "length": "м",
        "area": "м²",
        "volume": "м³",
        "weight": "кг",
        "temperature": "°C",
    },
}
