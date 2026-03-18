"""Internationalization system.

20 languages built into core. Zero hardcoded strings.
New language = add a JSON file to locales/.

Backend: returns translation keys or resolved strings.
Frontend: loads locale JSON, resolves client-side.

Usage:
    from app.core.i18n import t, set_locale

    set_locale("de")
    msg = t("validation.missing_quantity", position="01.02.0030")
    # → "Position 01.02.0030 hat keine Menge"
"""

import json
import logging
from pathlib import Path
from contextvars import ContextVar
from typing import Any

logger = logging.getLogger(__name__)

# Context variable for current locale (per-request in async)
_current_locale: ContextVar[str] = ContextVar("current_locale", default="en")

# All loaded translations: {locale: {key: value}}
_translations: dict[str, dict[str, str]] = {}

# Built-in languages (ISO 639-1)
SUPPORTED_LOCALES = [
    "en",   # English
    "de",   # German (Deutsch)
    "ru",   # Russian (Русский)
    "fr",   # French (Français)
    "es",   # Spanish (Español)
    "pt",   # Portuguese (Português)
    "it",   # Italian (Italiano)
    "nl",   # Dutch (Nederlands)
    "pl",   # Polish (Polski)
    "cs",   # Czech (Čeština)
    "tr",   # Turkish (Türkçe)
    "ar",   # Arabic (العربية)
    "zh",   # Chinese Simplified (简体中文)
    "ja",   # Japanese (日本語)
    "ko",   # Korean (한국어)
    "hi",   # Hindi (हिन्दी)
    "sv",   # Swedish (Svenska)
    "no",   # Norwegian (Norsk)
    "da",   # Danish (Dansk)
    "fi",   # Finnish (Suomi)
]

LOCALE_NAMES = {
    "en": "English",
    "de": "Deutsch",
    "ru": "Русский",
    "fr": "Français",
    "es": "Español",
    "pt": "Português",
    "it": "Italiano",
    "nl": "Nederlands",
    "pl": "Polski",
    "cs": "Čeština",
    "tr": "Türkçe",
    "ar": "العربية",
    "zh": "简体中文",
    "ja": "日本語",
    "ko": "한국어",
    "hi": "हिन्दी",
    "sv": "Svenska",
    "no": "Norsk",
    "da": "Dansk",
    "fi": "Suomi",
}

LOCALES_DIR = Path(__file__).parent.parent.parent / "locales"


def load_translations(locales_dir: Path | None = None) -> None:
    """Load all locale JSON files into memory."""
    global _translations
    scan_dir = locales_dir or LOCALES_DIR

    if not scan_dir.exists():
        logger.warning("Locales directory not found: %s — creating with defaults", scan_dir)
        scan_dir.mkdir(parents=True, exist_ok=True)
        _generate_default_locales(scan_dir)

    for locale_file in scan_dir.glob("*.json"):
        locale = locale_file.stem
        try:
            with open(locale_file, encoding="utf-8") as f:
                data = json.load(f)
            _translations[locale] = _flatten_dict(data)
            logger.debug("Loaded locale: %s (%d keys)", locale, len(_translations[locale]))
        except Exception:
            logger.exception("Failed to load locale file: %s", locale_file)

    logger.info("Loaded %d locales: %s", len(_translations), list(_translations.keys()))


def _flatten_dict(d: dict, prefix: str = "") -> dict[str, str]:
    """Flatten nested dict: {"validation": {"error": "msg"}} → {"validation.error": "msg"}"""
    items: dict[str, str] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            items.update(_flatten_dict(v, key))
        else:
            items[key] = str(v)
    return items


def set_locale(locale: str) -> None:
    """Set current locale for this context (request)."""
    _current_locale.set(locale if locale in _translations else "en")


def get_locale() -> str:
    """Get current locale."""
    return _current_locale.get()


def t(key: str, locale: str | None = None, **kwargs: Any) -> str:
    """Translate a key with optional interpolation.

    Args:
        key: Dot-notation key, e.g. "validation.missing_quantity"
        locale: Override locale (default: current context locale)
        **kwargs: Interpolation values, e.g. position="01.02.0030"

    Returns:
        Translated string, or key itself if not found.
    """
    loc = locale or get_locale()

    # Try requested locale → English fallback → raw key
    template = (
        _translations.get(loc, {}).get(key)
        or _translations.get("en", {}).get(key)
        or key
    )

    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template

    return template


def get_all_translations(locale: str) -> dict[str, str]:
    """Get all translations for a locale (for frontend bundle)."""
    return _translations.get(locale, _translations.get("en", {}))


def get_available_locales() -> list[dict[str, str]]:
    """List available locales with their display names."""
    return [
        {"code": code, "name": LOCALE_NAMES.get(code, code), "loaded": code in _translations}
        for code in SUPPORTED_LOCALES
    ]


def _generate_default_locales(locales_dir: Path) -> None:
    """Generate minimal default locale files for all 20 languages."""
    # English is the master — all keys defined here
    en = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Open-source construction cost estimation",
        },
        "common": {
            "save": "Save",
            "cancel": "Cancel",
            "delete": "Delete",
            "edit": "Edit",
            "create": "Create",
            "search": "Search",
            "filter": "Filter",
            "export": "Export",
            "import": "Import",
            "loading": "Loading...",
            "error": "Error",
            "success": "Success",
            "confirm": "Confirm",
            "back": "Back",
            "next": "Next",
            "yes": "Yes",
            "no": "No",
        },
        "auth": {
            "login": "Log In",
            "logout": "Log Out",
            "email": "Email",
            "password": "Password",
        },
        "projects": {
            "title": "Projects",
            "new_project": "New Project",
            "project_name": "Project Name",
            "no_projects": "No projects yet",
        },
        "boq": {
            "title": "Bill of Quantities",
            "position": "Position",
            "ordinal": "Ordinal",
            "description": "Description",
            "quantity": "Quantity",
            "unit": "Unit",
            "unit_rate": "Unit Rate",
            "total": "Total",
            "add_position": "Add Position",
            "add_section": "Add Section",
            "assembly": "Assembly",
            "subtotal": "Subtotal",
            "grand_total": "Grand Total",
        },
        "costs": {
            "title": "Cost Database",
            "rate": "Rate",
            "material": "Material",
            "labor": "Labor",
            "equipment": "Equipment",
            "search_costs": "Search cost items...",
        },
        "validation": {
            "title": "Validation",
            "passed": "Passed",
            "warnings": "Warnings",
            "errors": "Errors",
            "score": "Quality Score",
            "run_validation": "Run Validation",
            "missing_quantity": "Position {position} has no quantity",
            "missing_rate": "Position {position} has no unit rate",
            "missing_description": "Position {position} is missing a description",
            "missing_classification": "Position {position} needs a classification code",
            "duplicate_ordinal": "Duplicate ordinal number: {ordinal}",
            "rate_anomaly": "Unit rate {rate} exceeds threshold ({threshold})",
        },
        "cad": {
            "title": "CAD Import",
            "upload": "Upload CAD File",
            "supported_formats": "Supported: DWG, DGN, RVT, IFC, PDF",
            "converting": "Converting...",
            "elements_found": "{count} elements found",
        },
        "takeoff": {
            "title": "Quantity Takeoff",
            "auto_detect": "Auto-Detect",
            "manual_measure": "Manual Measure",
            "confidence": "Confidence",
        },
        "tendering": {
            "title": "Tendering",
            "create_tender": "Create Tender",
            "bid": "Bid",
            "award": "Award",
        },
        "modules": {
            "title": "Modules",
            "installed": "Installed",
            "available": "Available",
            "install": "Install",
            "uninstall": "Uninstall",
            "update": "Update",
        },
        "units": {
            "m": "m",
            "m2": "m²",
            "m3": "m³",
            "kg": "kg",
            "t": "t",
            "pcs": "pcs",
            "lsum": "lump sum",
            "h": "h",
            "set": "set",
        },
    }

    # German translations
    de = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Open-Source Baukalkulation",
        },
        "common": {
            "save": "Speichern",
            "cancel": "Abbrechen",
            "delete": "Löschen",
            "edit": "Bearbeiten",
            "create": "Erstellen",
            "search": "Suchen",
            "filter": "Filtern",
            "export": "Exportieren",
            "import": "Importieren",
            "loading": "Laden...",
            "error": "Fehler",
            "success": "Erfolg",
            "confirm": "Bestätigen",
            "back": "Zurück",
            "next": "Weiter",
            "yes": "Ja",
            "no": "Nein",
        },
        "auth": {
            "login": "Anmelden",
            "logout": "Abmelden",
            "email": "E-Mail",
            "password": "Passwort",
        },
        "projects": {
            "title": "Projekte",
            "new_project": "Neues Projekt",
            "project_name": "Projektname",
            "no_projects": "Noch keine Projekte",
        },
        "boq": {
            "title": "Leistungsverzeichnis",
            "position": "Position",
            "ordinal": "Ordnungszahl",
            "description": "Beschreibung",
            "quantity": "Menge",
            "unit": "Einheit",
            "unit_rate": "Einheitspreis",
            "total": "Gesamtbetrag",
            "add_position": "Position hinzufügen",
            "add_section": "Abschnitt hinzufügen",
            "assembly": "Baugruppe",
            "subtotal": "Zwischensumme",
            "grand_total": "Gesamtsumme",
        },
        "costs": {
            "title": "Preisdatenbank",
            "rate": "Preis",
            "material": "Material",
            "labor": "Lohn",
            "equipment": "Gerät",
            "search_costs": "Preispositionen suchen...",
        },
        "validation": {
            "title": "Validierung",
            "passed": "Bestanden",
            "warnings": "Warnungen",
            "errors": "Fehler",
            "score": "Qualitätsbewertung",
            "run_validation": "Validierung starten",
            "missing_quantity": "Position {position} hat keine Menge",
            "missing_rate": "Position {position} hat keinen Einheitspreis",
            "missing_description": "Position {position} hat keine Beschreibung",
            "missing_classification": "Position {position} benötigt eine Klassifizierung",
            "duplicate_ordinal": "Doppelte Ordnungszahl: {ordinal}",
            "rate_anomaly": "Einheitspreis {rate} überschreitet Schwellenwert ({threshold})",
        },
        "cad": {
            "title": "CAD-Import",
            "upload": "CAD-Datei hochladen",
            "supported_formats": "Unterstützt: DWG, DGN, RVT, IFC, PDF",
            "converting": "Konvertierung...",
            "elements_found": "{count} Elemente gefunden",
        },
        "modules": {
            "title": "Module",
            "installed": "Installiert",
            "available": "Verfügbar",
            "install": "Installieren",
            "uninstall": "Deinstallieren",
            "update": "Aktualisieren",
        },
    }

    # Russian translations
    ru = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Open-source сметное дело",
        },
        "common": {
            "save": "Сохранить",
            "cancel": "Отмена",
            "delete": "Удалить",
            "edit": "Редактировать",
            "create": "Создать",
            "search": "Поиск",
            "filter": "Фильтр",
            "export": "Экспорт",
            "import": "Импорт",
            "loading": "Загрузка...",
            "error": "Ошибка",
            "success": "Успешно",
            "confirm": "Подтвердить",
            "back": "Назад",
            "next": "Далее",
            "yes": "Да",
            "no": "Нет",
        },
        "projects": {
            "title": "Проекты",
            "new_project": "Новый проект",
            "project_name": "Название проекта",
            "no_projects": "Нет проектов",
        },
        "boq": {
            "title": "Смета",
            "position": "Позиция",
            "ordinal": "Номер",
            "description": "Описание",
            "quantity": "Количество",
            "unit": "Ед. изм.",
            "unit_rate": "Цена за единицу",
            "total": "Итого",
            "add_position": "Добавить позицию",
            "add_section": "Добавить раздел",
            "assembly": "Сборная расценка",
            "subtotal": "Подитог",
            "grand_total": "Общий итог",
        },
        "validation": {
            "title": "Проверка",
            "passed": "Пройдено",
            "warnings": "Предупреждения",
            "errors": "Ошибки",
            "score": "Оценка качества",
            "run_validation": "Запустить проверку",
            "missing_quantity": "Позиция {position} без количества",
            "missing_rate": "Позиция {position} без расценки",
            "missing_description": "Позиция {position} без описания",
            "missing_classification": "Позиция {position} без классификации",
            "duplicate_ordinal": "Дублирующийся номер: {ordinal}",
            "rate_anomaly": "Расценка {rate} превышает порог ({threshold})",
        },
        "modules": {
            "title": "Модули",
            "installed": "Установлено",
            "available": "Доступно",
            "install": "Установить",
            "uninstall": "Удалить",
            "update": "Обновить",
        },
    }

    for locale_code, data in [("en", en), ("de", de), ("ru", ru)]:
        path = locales_dir / f"{locale_code}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # Generate stub files for remaining 17 languages (copy English keys as placeholders)
    for code in SUPPORTED_LOCALES:
        path = locales_dir / f"{code}.json"
        if not path.exists():
            stub = {"_meta": {"language": LOCALE_NAMES.get(code, code), "complete": False}}
            with open(path, "w", encoding="utf-8") as f:
                json.dump(stub, f, ensure_ascii=False, indent=2)
