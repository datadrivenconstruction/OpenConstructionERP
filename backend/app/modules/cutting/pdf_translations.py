# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""String catalogue for the printed cutting list and its workbook.

The cutting list is what goes to the saw: one row per stock piece with the cuts
taken from it, the offcut kept and the scrap. Its fixed strings live here, next
to the renderer, joined with the shared page furniture. Languages the shared
furniture carries are in the catalogue; any other request renders in English.
"""

from __future__ import annotations

from typing import Any

from app.core.register_export import FORM_FURNITURE, DocumentCatalogue, export_filename

DEFAULT_PDF_LOCALE = "en"

_STRINGS: dict[str, dict[str, str]] = {
    "en": {
        "register_title": "Cutting List",
        "job": "Job",
        "material": "Material",
        "kerf": "Kerf (mm)",
        "yield": "Yield",
        "waste": "Waste",
        "stock_count": "Stock pieces",
        "cost": "Stock cost",
        "col_no": "No.",
        "col_stock": "Stock",
        "col_size": "Size (mm)",
        "col_cuts": "Cuts (mark length x count)",
        "col_offcut": "Offcut (mm)",
        "col_scrap": "Scrap",
        "col_cost": "Cost",
        "col_source": "Source",
        "source_inventory": "Inventory offcut",
        "source_purchase": "Purchase",
        "unplaced": "Unplaced pieces",
        "empty": "The plan has no stock pieces.",
        "register_filename": "cutting-list",
    },
    "de": {
        "register_title": "Zuschnittliste",
        "job": "Auftrag",
        "material": "Material",
        "kerf": "Schnittfuge (mm)",
        "yield": "Ausnutzung",
        "waste": "Verschnitt",
        "stock_count": "Rohteile",
        "cost": "Materialkosten",
        "col_no": "Nr.",
        "col_stock": "Rohteil",
        "col_size": "Maß (mm)",
        "col_cuts": "Zuschnitte (Position Länge x Anzahl)",
        "col_offcut": "Reststück (mm)",
        "col_scrap": "Abfall",
        "col_cost": "Kosten",
        "col_source": "Herkunft",
        "source_inventory": "Reststück aus Lager",
        "source_purchase": "Einkauf",
        "unplaced": "Nicht platzierte Teile",
        "empty": "Der Plan enthält keine Rohteile.",
        "register_filename": "zuschnittliste",
    },
    "ru": {
        "register_title": "Карта раскроя",
        "job": "Задание",
        "material": "Материал",
        "kerf": "Пропил (мм)",
        "yield": "Выход",
        "waste": "Отходы",
        "stock_count": "Заготовок",
        "cost": "Стоимость заготовок",
        "col_no": "№",
        "col_stock": "Заготовка",
        "col_size": "Размер (мм)",
        "col_cuts": "Резы (марка длина x кол-во)",
        "col_offcut": "Деловой остаток (мм)",
        "col_scrap": "Отход",
        "col_cost": "Стоимость",
        "col_source": "Источник",
        "source_inventory": "Остаток со склада",
        "source_purchase": "Закупка",
        "unplaced": "Неразмещённые детали",
        "empty": "В плане нет заготовок.",
        "register_filename": "karta-raskroya",
    },
    "tr": {
        "register_title": "Kesim Listesi",
        "job": "İş",
        "material": "Malzeme",
        "kerf": "Kesim payı (mm)",
        "yield": "Verim",
        "waste": "Fire",
        "stock_count": "Stok parça",
        "cost": "Stok maliyeti",
        "col_no": "No.",
        "col_stock": "Stok",
        "col_size": "Ölçü (mm)",
        "col_cuts": "Kesimler (poz uzunluk x adet)",
        "col_offcut": "Artık parça (mm)",
        "col_scrap": "Hurda",
        "col_cost": "Maliyet",
        "col_source": "Kaynak",
        "source_inventory": "Depodan artık parça",
        "source_purchase": "Satın alma",
        "unplaced": "Yerleştirilemeyen parçalar",
        "empty": "Planda stok parça yok.",
        "register_filename": "kesim-listesi",
    },
}

CATALOGUE = DocumentCatalogue(_STRINGS, default=DEFAULT_PDF_LOCALE, furniture=FORM_FURNITURE)


def resolve_pdf_locale(locale_param: str | None, accept_language: str | None) -> str:
    """Pick the document language: ``?locale=``, then ``Accept-Language``, then English."""
    return CATALOGUE.resolve(locale_param, accept_language)


def tr(locale: str, key: str, **params: Any) -> str:
    """Resolve ``key`` for ``locale``, falling back to English, then the key."""
    return CATALOGUE.tr(locale, key, **params)


def cutting_list_filename(locale: str, extension: str) -> str:
    """Download filename for the cutting list, e.g. ``cutting-list.pdf``."""
    return export_filename(tr(locale, "register_filename"), "cutting-list", extension)


__all__ = ["CATALOGUE", "DEFAULT_PDF_LOCALE", "cutting_list_filename", "resolve_pdf_locale", "tr"]
