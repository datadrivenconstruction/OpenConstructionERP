"""Wording of clarifying questions. English is the base; German and Russian are shipped now,
other locales fall back to English until the locale pass (card L1) fills them in.
"""

from __future__ import annotations

LABELS: dict[str, dict[str, str]] = {
    "en": {
        "/country": "country of the project",
        "/locale": "language of the brief",
        "/depth_level": "level of detail (D1-D5)",
        "/use/category": "building use",
        "/massing/floors_above": "number of floors above ground",
        "/massing/floors_below": "number of basement floors",
        "/massing/floor_height_m": "floor height (m)",
        "/massing/ground_floor_height_m": "ground floor height (m)",
        "/massing/gross_floor_area_m2": "gross floor area (m2)",
        "/massing/footprint/width_m": "footprint width (m)",
        "/massing/footprint/depth_m": "footprint depth (m)",
        "/massing/lift": "lift",
        "/site/address": "site address",
        "/site/max_height_m": "maximum building height (m)",
        "/site/max_floors": "maximum number of floors",
        "/site/floor_area_ratio_max": "maximum floor area ratio",
        "/site/site_coverage_max": "maximum site coverage (0-1)",
        "/programme/units": "dwelling or office units",
        "/programme/parking_spaces": "number of parking spaces",
        "/structure/system": "structural system",
        "/structure/foundation": "foundation type",
        "/envelope/roof": "roof shape",
        "/quality_level": "quality level",
        "/budget/amount": "budget amount",
        "/budget/currency": "budget currency",
        "/budget/includes_vat": "budget includes VAT",
    },
    "de": {
        "/country": "Land des Projekts",
        "/locale": "Sprache des Briefings",
        "/depth_level": "Detailstufe (D1-D5)",
        "/use/category": "Gebäudenutzung",
        "/massing/floors_above": "Anzahl der oberirdischen Geschosse",
        "/massing/floors_below": "Anzahl der Untergeschosse",
        "/massing/floor_height_m": "Geschosshöhe (m)",
        "/massing/ground_floor_height_m": "Höhe des Erdgeschosses (m)",
        "/massing/gross_floor_area_m2": "Brutto-Grundfläche (m2)",
        "/massing/footprint/width_m": "Breite des Grundrisses (m)",
        "/massing/footprint/depth_m": "Tiefe des Grundrisses (m)",
        "/massing/lift": "Aufzug",
        "/site/address": "Adresse des Grundstücks",
        "/site/max_height_m": "maximale Gebäudehöhe (m)",
        "/site/max_floors": "maximale Geschosszahl",
        "/site/floor_area_ratio_max": "maximale Geschossflächenzahl",
        "/site/site_coverage_max": "maximale Grundflächenzahl (0-1)",
        "/programme/units": "Wohn- oder Büroeinheiten",
        "/programme/parking_spaces": "Anzahl der Stellplätze",
        "/structure/system": "Tragwerk",
        "/structure/foundation": "Gründungsart",
        "/envelope/roof": "Dachform",
        "/quality_level": "Qualitätsstufe",
        "/budget/amount": "Höhe des Budgets",
        "/budget/currency": "Währung des Budgets",
        "/budget/includes_vat": "Budget inklusive MwSt",
    },
    "ru": {
        "/country": "страна проекта",
        "/locale": "язык задания",
        "/depth_level": "уровень детализации (D1-D5)",
        "/use/category": "назначение здания",
        "/massing/floors_above": "число надземных этажей",
        "/massing/floors_below": "число подземных этажей",
        "/massing/floor_height_m": "высота этажа (м)",
        "/massing/ground_floor_height_m": "высота первого этажа (м)",
        "/massing/gross_floor_area_m2": "общая площадь (м2)",
        "/massing/footprint/width_m": "ширина здания в плане (м)",
        "/massing/footprint/depth_m": "глубина здания в плане (м)",
        "/massing/lift": "лифт",
        "/site/address": "адрес участка",
        "/site/max_height_m": "предельная высота здания (м)",
        "/site/max_floors": "предельная этажность",
        "/site/floor_area_ratio_max": "предельный коэффициент плотности застройки",
        "/site/site_coverage_max": "предельный коэффициент застройки (0-1)",
        "/programme/units": "квартиры или офисные блоки",
        "/programme/parking_spaces": "число машино-мест",
        "/structure/system": "несущая система",
        "/structure/foundation": "тип фундамента",
        "/envelope/roof": "форма крыши",
        "/quality_level": "уровень качества",
        "/budget/amount": "сумма бюджета",
        "/budget/currency": "валюта бюджета",
        "/budget/includes_vat": "бюджет с НДС",
    },
}

TEMPLATES: dict[str, dict[str, str]] = {
    "en": {
        "missing": "The documents do not state the {label}. What is it?",
        "contradiction": "The documents give different values for the {label}: {detail}. Which one applies?",
        "out_of_range": "A value found for the {label} is outside the allowed range ({detail}). What is the correct value?",
        "ambiguous": "The {label} is not clear from the documents: {detail}. Which is right?",
    },
    "de": {
        "missing": "In den Unterlagen steht nichts zu: {label}. Was gilt?",
        "contradiction": "Die Unterlagen nennen verschiedene Werte für {label}: {detail}. Welcher gilt?",
        "out_of_range": "Für {label} wurde ein Wert außerhalb des zulässigen Bereichs gefunden ({detail}). Welcher Wert ist richtig?",
        "ambiguous": "{label} ist aus den Unterlagen nicht eindeutig: {detail}. Was stimmt?",
    },
    "ru": {
        "missing": "В документах не указано: {label}. Какое значение?",
        "contradiction": "В документах разные значения для поля «{label}»: {detail}. Какое верное?",
        "out_of_range": "Для поля «{label}» найдено значение вне допустимого диапазона ({detail}). Какое значение верное?",
        "ambiguous": "Поле «{label}» неоднозначно в документах: {detail}. Что верно?",
    },
}


def _lang(locale: str) -> str:
    base = (locale or "en").split("-")[0].lower()
    return base if base in TEMPLATES else "en"


def field_label(locale: str, pointer: str) -> str:
    lang = _lang(locale)
    return LABELS[lang].get(pointer) or LABELS["en"].get(pointer) or pointer.rsplit("/", 1)[-1].replace("_", " ")


def question_text(locale: str, pointer: str, reason: str, detail: str = "") -> str:
    lang = _lang(locale)
    template = TEMPLATES[lang].get(reason) or TEMPLATES["en"][reason]
    return template.format(label=field_label(locale, pointer), detail=detail or "-")
