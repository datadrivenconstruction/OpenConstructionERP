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
from contextvars import ContextVar
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Context variable for current locale (per-request in async)
_current_locale: ContextVar[str] = ContextVar("current_locale", default="en")

# All loaded translations: {locale: {key: value}}
_translations: dict[str, dict[str, str]] = {}

# Built-in languages (ISO 639-1)
SUPPORTED_LOCALES = [
    "en",  # English
    "de",  # German (Deutsch)
    "ru",  # Russian (Русский)
    "fr",  # French (Français)
    "es",  # Spanish (Español)
    "pt",  # Portuguese (Português)
    "it",  # Italian (Italiano)
    "nl",  # Dutch (Nederlands)
    "pl",  # Polish (Polski)
    "cs",  # Czech (Čeština)
    "tr",  # Turkish (Türkçe)
    "ar",  # Arabic (العربية)
    "zh",  # Chinese Simplified (简体中文)
    "ja",  # Japanese (日本語)
    "ko",  # Korean (한국어)
    "hi",  # Hindi (हिन्दी)
    "sv",  # Swedish (Svenska)
    "no",  # Norwegian (Norsk)
    "da",  # Danish (Dansk)
    "fi",  # Finnish (Suomi)
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
    template = _translations.get(loc, {}).get(key) or _translations.get("en", {}).get(key) or key

    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError):
            return template

    return template


def get_all_translations(locale: str) -> dict[str, str]:
    """Get all translations for a locale (for frontend bundle)."""
    return _translations.get(locale, _translations.get("en", {}))


def get_available_locales() -> list[dict[str, object]]:
    """List available locales with their display names."""
    return [
        {"code": code, "name": LOCALE_NAMES.get(code, code), "loaded": code in _translations}
        for code in SUPPORTED_LOCALES
    ]


def _generate_default_locales(locales_dir: Path) -> None:
    """Generate complete locale files for all 20 supported languages."""
    # -------------------------------------------------------------------------
    # English — master locale. All keys defined here.
    # -------------------------------------------------------------------------
    en: dict[str, dict[str, str]] = {
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
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "pcs",
            "lsum": "lump sum",
            "h": "h",
            "set": "set",
        },
    }

    # -------------------------------------------------------------------------
    # German (Deutsch) — Baukalkulation / HOAI / VOB terminology
    # -------------------------------------------------------------------------
    de: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Open-Source Baukalkulation",
        },
        "common": {
            "save": "Speichern",
            "cancel": "Abbrechen",
            "delete": "L\u00f6schen",
            "edit": "Bearbeiten",
            "create": "Erstellen",
            "search": "Suchen",
            "filter": "Filtern",
            "export": "Exportieren",
            "import": "Importieren",
            "loading": "Laden...",
            "error": "Fehler",
            "success": "Erfolg",
            "confirm": "Best\u00e4tigen",
            "back": "Zur\u00fcck",
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
            "add_position": "Position hinzuf\u00fcgen",
            "add_section": "Abschnitt hinzuf\u00fcgen",
            "assembly": "Baugruppe",
            "subtotal": "Zwischensumme",
            "grand_total": "Gesamtsumme",
        },
        "costs": {
            "title": "Preisdatenbank",
            "rate": "Preis",
            "material": "Material",
            "labor": "Lohn",
            "equipment": "Ger\u00e4t",
            "search_costs": "Preispositionen suchen...",
        },
        "validation": {
            "title": "Validierung",
            "passed": "Bestanden",
            "warnings": "Warnungen",
            "errors": "Fehler",
            "score": "Qualit\u00e4tsbewertung",
            "run_validation": "Validierung starten",
            "missing_quantity": "Position {position} hat keine Menge",
            "missing_rate": "Position {position} hat keinen Einheitspreis",
            "missing_description": "Position {position} hat keine Beschreibung",
            "missing_classification": "Position {position} ben\u00f6tigt eine Klassifizierung",
            "duplicate_ordinal": "Doppelte Ordnungszahl: {ordinal}",
            "rate_anomaly": "Einheitspreis {rate} \u00fcberschreitet Schwellenwert ({threshold})",
        },
        "cad": {
            "title": "CAD-Import",
            "upload": "CAD-Datei hochladen",
            "supported_formats": "Unterst\u00fctzt: DWG, DGN, RVT, IFC, PDF",
            "converting": "Konvertierung...",
            "elements_found": "{count} Elemente gefunden",
        },
        "takeoff": {
            "title": "Mengenermittlung",
            "auto_detect": "Automatische Erkennung",
            "manual_measure": "Manuelles Aufma\u00df",
            "confidence": "Konfidenz",
        },
        "tendering": {
            "title": "Ausschreibung",
            "create_tender": "Ausschreibung erstellen",
            "bid": "Angebot",
            "award": "Zuschlag",
        },
        "modules": {
            "title": "Module",
            "installed": "Installiert",
            "available": "Verf\u00fcgbar",
            "install": "Installieren",
            "uninstall": "Deinstallieren",
            "update": "Aktualisieren",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "Stk",
            "lsum": "pauschal",
            "h": "Std",
            "set": "Set",
        },
    }

    # -------------------------------------------------------------------------
    # Russian (\u0420\u0443\u0441\u0441\u043a\u0438\u0439) — \u0421\u043c\u0435\u0442\u043d\u043e\u0435 \u0434\u0435\u043b\u043e / \u0413\u042d\u0421\u041d / \u0424\u0415\u0420 terminology
    # -------------------------------------------------------------------------
    ru: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Open-source \u0441\u043c\u0435\u0442\u043d\u043e\u0435 \u0434\u0435\u043b\u043e",
        },
        "common": {
            "save": "\u0421\u043e\u0445\u0440\u0430\u043d\u0438\u0442\u044c",
            "cancel": "\u041e\u0442\u043c\u0435\u043d\u0430",
            "delete": "\u0423\u0434\u0430\u043b\u0438\u0442\u044c",
            "edit": "\u0420\u0435\u0434\u0430\u043a\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c",
            "create": "\u0421\u043e\u0437\u0434\u0430\u0442\u044c",
            "search": "\u041f\u043e\u0438\u0441\u043a",
            "filter": "\u0424\u0438\u043b\u044c\u0442\u0440",
            "export": "\u042d\u043a\u0441\u043f\u043e\u0440\u0442",
            "import": "\u0418\u043c\u043f\u043e\u0440\u0442",
            "loading": "\u0417\u0430\u0433\u0440\u0443\u0437\u043a\u0430...",
            "error": "\u041e\u0448\u0438\u0431\u043a\u0430",
            "success": "\u0423\u0441\u043f\u0435\u0448\u043d\u043e",
            "confirm": "\u041f\u043e\u0434\u0442\u0432\u0435\u0440\u0434\u0438\u0442\u044c",
            "back": "\u041d\u0430\u0437\u0430\u0434",
            "next": "\u0414\u0430\u043b\u0435\u0435",
            "yes": "\u0414\u0430",
            "no": "\u041d\u0435\u0442",
        },
        "auth": {
            "login": "\u0412\u043e\u0439\u0442\u0438",
            "logout": "\u0412\u044b\u0439\u0442\u0438",
            "email": "\u042d\u043b. \u043f\u043e\u0447\u0442\u0430",
            "password": "\u041f\u0430\u0440\u043e\u043b\u044c",
        },
        "projects": {
            "title": "\u041f\u0440\u043e\u0435\u043a\u0442\u044b",
            "new_project": "\u041d\u043e\u0432\u044b\u0439 \u043f\u0440\u043e\u0435\u043a\u0442",
            "project_name": "\u041d\u0430\u0437\u0432\u0430\u043d\u0438\u0435 \u043f\u0440\u043e\u0435\u043a\u0442\u0430",
            "no_projects": "\u041d\u0435\u0442 \u043f\u0440\u043e\u0435\u043a\u0442\u043e\u0432",
        },
        "boq": {
            "title": "\u0421\u043c\u0435\u0442\u0430",
            "position": "\u041f\u043e\u0437\u0438\u0446\u0438\u044f",
            "ordinal": "\u041d\u043e\u043c\u0435\u0440",
            "description": "\u041e\u043f\u0438\u0441\u0430\u043d\u0438\u0435",
            "quantity": "\u041a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u043e",
            "unit": "\u0415\u0434. \u0438\u0437\u043c.",
            "unit_rate": "\u0426\u0435\u043d\u0430 \u0437\u0430 \u0435\u0434\u0438\u043d\u0438\u0446\u0443",
            "total": "\u0418\u0442\u043e\u0433\u043e",
            "add_position": "\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u043f\u043e\u0437\u0438\u0446\u0438\u044e",
            "add_section": "\u0414\u043e\u0431\u0430\u0432\u0438\u0442\u044c \u0440\u0430\u0437\u0434\u0435\u043b",
            "assembly": "\u0421\u0431\u043e\u0440\u043d\u0430\u044f \u0440\u0430\u0441\u0446\u0435\u043d\u043a\u0430",
            "subtotal": "\u041f\u043e\u0434\u0438\u0442\u043e\u0433",
            "grand_total": "\u041e\u0431\u0449\u0438\u0439 \u0438\u0442\u043e\u0433",
        },
        "costs": {
            "title": "\u0411\u0430\u0437\u0430 \u0440\u0430\u0441\u0446\u0435\u043d\u043e\u043a",
            "rate": "\u0420\u0430\u0441\u0446\u0435\u043d\u043a\u0430",
            "material": "\u041c\u0430\u0442\u0435\u0440\u0438\u0430\u043b",
            "labor": "\u0420\u0430\u0431\u043e\u0442\u0430",
            "equipment": "\u041c\u0435\u0445\u0430\u043d\u0438\u0437\u043c\u044b",
            "search_costs": "\u041f\u043e\u0438\u0441\u043a \u0440\u0430\u0441\u0446\u0435\u043d\u043e\u043a...",
        },
        "validation": {
            "title": "\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430",
            "passed": "\u041f\u0440\u043e\u0439\u0434\u0435\u043d\u043e",
            "warnings": "\u041f\u0440\u0435\u0434\u0443\u043f\u0440\u0435\u0436\u0434\u0435\u043d\u0438\u044f",
            "errors": "\u041e\u0448\u0438\u0431\u043a\u0438",
            "score": "\u041e\u0446\u0435\u043d\u043a\u0430 \u043a\u0430\u0447\u0435\u0441\u0442\u0432\u0430",
            "run_validation": "\u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0443",
            "missing_quantity": "\u041f\u043e\u0437\u0438\u0446\u0438\u044f {position} \u0431\u0435\u0437 \u043a\u043e\u043b\u0438\u0447\u0435\u0441\u0442\u0432\u0430",
            "missing_rate": "\u041f\u043e\u0437\u0438\u0446\u0438\u044f {position} \u0431\u0435\u0437 \u0440\u0430\u0441\u0446\u0435\u043d\u043a\u0438",
            "missing_description": "\u041f\u043e\u0437\u0438\u0446\u0438\u044f {position} \u0431\u0435\u0437 \u043e\u043f\u0438\u0441\u0430\u043d\u0438\u044f",
            "missing_classification": "\u041f\u043e\u0437\u0438\u0446\u0438\u044f {position} \u0431\u0435\u0437 \u043a\u043b\u0430\u0441\u0441\u0438\u0444\u0438\u043a\u0430\u0446\u0438\u0438",
            "duplicate_ordinal": "\u0414\u0443\u0431\u043b\u0438\u0440\u0443\u044e\u0449\u0438\u0439\u0441\u044f \u043d\u043e\u043c\u0435\u0440: {ordinal}",
            "rate_anomaly": "\u0420\u0430\u0441\u0446\u0435\u043d\u043a\u0430 {rate} \u043f\u0440\u0435\u0432\u044b\u0448\u0430\u0435\u0442 \u043f\u043e\u0440\u043e\u0433 ({threshold})",
        },
        "cad": {
            "title": "\u0418\u043c\u043f\u043e\u0440\u0442 CAD",
            "upload": "\u0417\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c CAD-\u0444\u0430\u0439\u043b",
            "supported_formats": "\u041f\u043e\u0434\u0434\u0435\u0440\u0436\u0438\u0432\u0430\u0435\u043c\u044b\u0435: DWG, DGN, RVT, IFC, PDF",
            "converting": "\u041a\u043e\u043d\u0432\u0435\u0440\u0442\u0430\u0446\u0438\u044f...",
            "elements_found": "\u041d\u0430\u0439\u0434\u0435\u043d\u043e \u044d\u043b\u0435\u043c\u0435\u043d\u0442\u043e\u0432: {count}",
        },
        "takeoff": {
            "title": "\u041f\u043e\u0434\u0441\u0447\u0451\u0442 \u043e\u0431\u044a\u0451\u043c\u043e\u0432",
            "auto_detect": "\u0410\u0432\u0442\u043e\u043e\u043f\u0440\u0435\u0434\u0435\u043b\u0435\u043d\u0438\u0435",
            "manual_measure": "\u0420\u0443\u0447\u043d\u043e\u0439 \u043e\u0431\u043c\u0435\u0440",
            "confidence": "\u0414\u043e\u0441\u0442\u043e\u0432\u0435\u0440\u043d\u043e\u0441\u0442\u044c",
        },
        "tendering": {
            "title": "\u0422\u0435\u043d\u0434\u0435\u0440\u044b",
            "create_tender": "\u0421\u043e\u0437\u0434\u0430\u0442\u044c \u0442\u0435\u043d\u0434\u0435\u0440",
            "bid": "\u041a\u043e\u043c\u043c\u0435\u0440\u0447\u0435\u0441\u043a\u043e\u0435 \u043f\u0440\u0435\u0434\u043b\u043e\u0436\u0435\u043d\u0438\u0435",
            "award": "\u041f\u0440\u0438\u0441\u0443\u0436\u0434\u0435\u043d\u0438\u0435",
        },
        "modules": {
            "title": "\u041c\u043e\u0434\u0443\u043b\u0438",
            "installed": "\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d\u043e",
            "available": "\u0414\u043e\u0441\u0442\u0443\u043f\u043d\u043e",
            "install": "\u0423\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c",
            "uninstall": "\u0423\u0434\u0430\u043b\u0438\u0442\u044c",
            "update": "\u041e\u0431\u043d\u043e\u0432\u0438\u0442\u044c",
        },
        "units": {
            "m": "\u043c",
            "m2": "\u043c\u00b2",
            "m3": "\u043c\u00b3",
            "kg": "\u043a\u0433",
            "t": "\u0442",
            "pcs": "\u0448\u0442",
            "lsum": "\u043f\u0430\u0443\u0448\u0430\u043b\u044c\u043d\u043e",
            "h": "\u0447",
            "set": "\u043a\u043e\u043c\u043f\u043b",
        },
    }

    # -------------------------------------------------------------------------
    # French (Fran\u00e7ais) — M\u00e9tr\u00e9 / DPGF / CCAG terminology
    # -------------------------------------------------------------------------
    fr: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Estimation des co\u00fbts de construction open-source",
        },
        "common": {
            "save": "Enregistrer",
            "cancel": "Annuler",
            "delete": "Supprimer",
            "edit": "Modifier",
            "create": "Cr\u00e9er",
            "search": "Rechercher",
            "filter": "Filtrer",
            "export": "Exporter",
            "import": "Importer",
            "loading": "Chargement...",
            "error": "Erreur",
            "success": "Succ\u00e8s",
            "confirm": "Confirmer",
            "back": "Retour",
            "next": "Suivant",
            "yes": "Oui",
            "no": "Non",
        },
        "auth": {
            "login": "Se connecter",
            "logout": "Se d\u00e9connecter",
            "email": "E-mail",
            "password": "Mot de passe",
        },
        "projects": {
            "title": "Projets",
            "new_project": "Nouveau projet",
            "project_name": "Nom du projet",
            "no_projects": "Aucun projet",
        },
        "boq": {
            "title": "Devis quantitatif",
            "position": "Poste",
            "ordinal": "Num\u00e9ro d\u2019ordre",
            "description": "D\u00e9signation",
            "quantity": "Quantit\u00e9",
            "unit": "Unit\u00e9",
            "unit_rate": "Prix unitaire",
            "total": "Total",
            "add_position": "Ajouter un poste",
            "add_section": "Ajouter une section",
            "assembly": "Ouvrage \u00e9l\u00e9mentaire",
            "subtotal": "Sous-total",
            "grand_total": "Total g\u00e9n\u00e9ral",
        },
        "costs": {
            "title": "Base de prix",
            "rate": "Prix",
            "material": "Mat\u00e9riau",
            "labor": "Main-d\u2019\u0153uvre",
            "equipment": "Mat\u00e9riel",
            "search_costs": "Rechercher des prix...",
        },
        "validation": {
            "title": "Validation",
            "passed": "R\u00e9ussi",
            "warnings": "Avertissements",
            "errors": "Erreurs",
            "score": "Score qualit\u00e9",
            "run_validation": "Lancer la validation",
            "missing_quantity": "Le poste {position} n\u2019a pas de quantit\u00e9",
            "missing_rate": "Le poste {position} n\u2019a pas de prix unitaire",
            "missing_description": "Le poste {position} n\u2019a pas de d\u00e9signation",
            "missing_classification": "Le poste {position} n\u00e9cessite un code de classification",
            "duplicate_ordinal": "Num\u00e9ro d\u2019ordre en double\u00a0: {ordinal}",
            "rate_anomaly": "Le prix unitaire {rate} d\u00e9passe le seuil ({threshold})",
        },
        "cad": {
            "title": "Import CAO",
            "upload": "T\u00e9l\u00e9verser un fichier CAO",
            "supported_formats": "Formats\u00a0: DWG, DGN, RVT, IFC, PDF",
            "converting": "Conversion en cours...",
            "elements_found": "{count} \u00e9l\u00e9ments trouv\u00e9s",
        },
        "takeoff": {
            "title": "M\u00e9tr\u00e9",
            "auto_detect": "D\u00e9tection automatique",
            "manual_measure": "Mesure manuelle",
            "confidence": "Confiance",
        },
        "tendering": {
            "title": "Appel d\u2019offres",
            "create_tender": "Cr\u00e9er un appel d\u2019offres",
            "bid": "Offre",
            "award": "Attribution",
        },
        "modules": {
            "title": "Modules",
            "installed": "Install\u00e9s",
            "available": "Disponibles",
            "install": "Installer",
            "uninstall": "D\u00e9sinstaller",
            "update": "Mettre \u00e0 jour",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "u",
            "lsum": "forfait",
            "h": "h",
            "set": "ens",
        },
    }

    # -------------------------------------------------------------------------
    # Spanish (Espa\u00f1ol) — Presupuesto de construcci\u00f3n terminology
    # -------------------------------------------------------------------------
    es: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Presupuesto de construcci\u00f3n de c\u00f3digo abierto",
        },
        "common": {
            "save": "Guardar",
            "cancel": "Cancelar",
            "delete": "Eliminar",
            "edit": "Editar",
            "create": "Crear",
            "search": "Buscar",
            "filter": "Filtrar",
            "export": "Exportar",
            "import": "Importar",
            "loading": "Cargando...",
            "error": "Error",
            "success": "\u00c9xito",
            "confirm": "Confirmar",
            "back": "Atr\u00e1s",
            "next": "Siguiente",
            "yes": "S\u00ed",
            "no": "No",
        },
        "auth": {
            "login": "Iniciar sesi\u00f3n",
            "logout": "Cerrar sesi\u00f3n",
            "email": "Correo electr\u00f3nico",
            "password": "Contrase\u00f1a",
        },
        "projects": {
            "title": "Proyectos",
            "new_project": "Nuevo proyecto",
            "project_name": "Nombre del proyecto",
            "no_projects": "A\u00fan no hay proyectos",
        },
        "boq": {
            "title": "Presupuesto",
            "position": "Partida",
            "ordinal": "N\u00famero de orden",
            "description": "Descripci\u00f3n",
            "quantity": "Medici\u00f3n",
            "unit": "Unidad",
            "unit_rate": "Precio unitario",
            "total": "Total",
            "add_position": "A\u00f1adir partida",
            "add_section": "A\u00f1adir cap\u00edtulo",
            "assembly": "Precio descompuesto",
            "subtotal": "Subtotal",
            "grand_total": "Total general",
        },
        "costs": {
            "title": "Base de precios",
            "rate": "Precio",
            "material": "Material",
            "labor": "Mano de obra",
            "equipment": "Maquinaria",
            "search_costs": "Buscar precios...",
        },
        "validation": {
            "title": "Validaci\u00f3n",
            "passed": "Aprobado",
            "warnings": "Advertencias",
            "errors": "Errores",
            "score": "Puntuaci\u00f3n de calidad",
            "run_validation": "Ejecutar validaci\u00f3n",
            "missing_quantity": "La partida {position} no tiene medici\u00f3n",
            "missing_rate": "La partida {position} no tiene precio unitario",
            "missing_description": "La partida {position} no tiene descripci\u00f3n",
            "missing_classification": "La partida {position} necesita un c\u00f3digo de clasificaci\u00f3n",
            "duplicate_ordinal": "N\u00famero de orden duplicado: {ordinal}",
            "rate_anomaly": "El precio unitario {rate} supera el umbral ({threshold})",
        },
        "cad": {
            "title": "Importaci\u00f3n CAD",
            "upload": "Subir archivo CAD",
            "supported_formats": "Formatos: DWG, DGN, RVT, IFC, PDF",
            "converting": "Convirtiendo...",
            "elements_found": "{count} elementos encontrados",
        },
        "takeoff": {
            "title": "Mediciones",
            "auto_detect": "Detecci\u00f3n autom\u00e1tica",
            "manual_measure": "Medici\u00f3n manual",
            "confidence": "Confianza",
        },
        "tendering": {
            "title": "Licitaci\u00f3n",
            "create_tender": "Crear licitaci\u00f3n",
            "bid": "Oferta",
            "award": "Adjudicaci\u00f3n",
        },
        "modules": {
            "title": "M\u00f3dulos",
            "installed": "Instalados",
            "available": "Disponibles",
            "install": "Instalar",
            "uninstall": "Desinstalar",
            "update": "Actualizar",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "ud",
            "lsum": "p.a.",
            "h": "h",
            "set": "jgo",
        },
    }

    # -------------------------------------------------------------------------
    # Portuguese (Portugu\u00eas) — Or\u00e7amento de obra terminology
    # -------------------------------------------------------------------------
    pt: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Or\u00e7amento de constru\u00e7\u00e3o de c\u00f3digo aberto",
        },
        "common": {
            "save": "Guardar",
            "cancel": "Cancelar",
            "delete": "Eliminar",
            "edit": "Editar",
            "create": "Criar",
            "search": "Pesquisar",
            "filter": "Filtrar",
            "export": "Exportar",
            "import": "Importar",
            "loading": "A carregar...",
            "error": "Erro",
            "success": "Sucesso",
            "confirm": "Confirmar",
            "back": "Voltar",
            "next": "Seguinte",
            "yes": "Sim",
            "no": "N\u00e3o",
        },
        "auth": {
            "login": "Iniciar sess\u00e3o",
            "logout": "Terminar sess\u00e3o",
            "email": "E-mail",
            "password": "Palavra-passe",
        },
        "projects": {
            "title": "Projetos",
            "new_project": "Novo projeto",
            "project_name": "Nome do projeto",
            "no_projects": "Ainda sem projetos",
        },
        "boq": {
            "title": "Mapa de quantidades",
            "position": "Artigo",
            "ordinal": "N\u00famero de ordem",
            "description": "Descri\u00e7\u00e3o",
            "quantity": "Quantidade",
            "unit": "Unidade",
            "unit_rate": "Pre\u00e7o unit\u00e1rio",
            "total": "Total",
            "add_position": "Adicionar artigo",
            "add_section": "Adicionar cap\u00edtulo",
            "assembly": "Pre\u00e7o composto",
            "subtotal": "Subtotal",
            "grand_total": "Total geral",
        },
        "costs": {
            "title": "Base de pre\u00e7os",
            "rate": "Pre\u00e7o",
            "material": "Material",
            "labor": "M\u00e3o de obra",
            "equipment": "Equipamento",
            "search_costs": "Pesquisar pre\u00e7os...",
        },
        "validation": {
            "title": "Valida\u00e7\u00e3o",
            "passed": "Aprovado",
            "warnings": "Avisos",
            "errors": "Erros",
            "score": "Pontua\u00e7\u00e3o de qualidade",
            "run_validation": "Executar valida\u00e7\u00e3o",
            "missing_quantity": "O artigo {position} n\u00e3o tem quantidade",
            "missing_rate": "O artigo {position} n\u00e3o tem pre\u00e7o unit\u00e1rio",
            "missing_description": "O artigo {position} n\u00e3o tem descri\u00e7\u00e3o",
            "missing_classification": "O artigo {position} necessita de c\u00f3digo de classifica\u00e7\u00e3o",
            "duplicate_ordinal": "N\u00famero de ordem duplicado: {ordinal}",
            "rate_anomaly": "O pre\u00e7o unit\u00e1rio {rate} excede o limiar ({threshold})",
        },
        "cad": {
            "title": "Importa\u00e7\u00e3o CAD",
            "upload": "Carregar ficheiro CAD",
            "supported_formats": "Formatos: DWG, DGN, RVT, IFC, PDF",
            "converting": "A converter...",
            "elements_found": "{count} elementos encontrados",
        },
        "takeoff": {
            "title": "Medi\u00e7\u00f5es",
            "auto_detect": "Dete\u00e7\u00e3o autom\u00e1tica",
            "manual_measure": "Medi\u00e7\u00e3o manual",
            "confidence": "Confian\u00e7a",
        },
        "tendering": {
            "title": "Concurso",
            "create_tender": "Criar concurso",
            "bid": "Proposta",
            "award": "Adjudica\u00e7\u00e3o",
        },
        "modules": {
            "title": "M\u00f3dulos",
            "installed": "Instalados",
            "available": "Dispon\u00edveis",
            "install": "Instalar",
            "uninstall": "Desinstalar",
            "update": "Atualizar",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "un",
            "lsum": "vg",
            "h": "h",
            "set": "cj",
        },
    }

    # -------------------------------------------------------------------------
    # Italian (Italiano) — Computo metrico / Capitolato terminology
    # -------------------------------------------------------------------------
    it: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Stima dei costi di costruzione open-source",
        },
        "common": {
            "save": "Salva",
            "cancel": "Annulla",
            "delete": "Elimina",
            "edit": "Modifica",
            "create": "Crea",
            "search": "Cerca",
            "filter": "Filtra",
            "export": "Esporta",
            "import": "Importa",
            "loading": "Caricamento...",
            "error": "Errore",
            "success": "Successo",
            "confirm": "Conferma",
            "back": "Indietro",
            "next": "Avanti",
            "yes": "S\u00ec",
            "no": "No",
        },
        "auth": {
            "login": "Accedi",
            "logout": "Esci",
            "email": "E-mail",
            "password": "Password",
        },
        "projects": {
            "title": "Progetti",
            "new_project": "Nuovo progetto",
            "project_name": "Nome del progetto",
            "no_projects": "Nessun progetto",
        },
        "boq": {
            "title": "Computo metrico",
            "position": "Voce",
            "ordinal": "Numero d\u2019ordine",
            "description": "Descrizione",
            "quantity": "Quantit\u00e0",
            "unit": "Unit\u00e0 di misura",
            "unit_rate": "Prezzo unitario",
            "total": "Totale",
            "add_position": "Aggiungi voce",
            "add_section": "Aggiungi sezione",
            "assembly": "Analisi prezzo",
            "subtotal": "Subtotale",
            "grand_total": "Totale generale",
        },
        "costs": {
            "title": "Prezzario",
            "rate": "Prezzo",
            "material": "Materiale",
            "labor": "Manodopera",
            "equipment": "Attrezzatura",
            "search_costs": "Cerca prezzi...",
        },
        "validation": {
            "title": "Validazione",
            "passed": "Superato",
            "warnings": "Avvisi",
            "errors": "Errori",
            "score": "Punteggio qualit\u00e0",
            "run_validation": "Avvia validazione",
            "missing_quantity": "La voce {position} non ha quantit\u00e0",
            "missing_rate": "La voce {position} non ha prezzo unitario",
            "missing_description": "La voce {position} non ha descrizione",
            "missing_classification": "La voce {position} necessita di un codice di classificazione",
            "duplicate_ordinal": "Numero d\u2019ordine duplicato: {ordinal}",
            "rate_anomaly": "Il prezzo unitario {rate} supera la soglia ({threshold})",
        },
        "cad": {
            "title": "Importazione CAD",
            "upload": "Carica file CAD",
            "supported_formats": "Formati: DWG, DGN, RVT, IFC, PDF",
            "converting": "Conversione in corso...",
            "elements_found": "{count} elementi trovati",
        },
        "takeoff": {
            "title": "Computo quantit\u00e0",
            "auto_detect": "Rilevamento automatico",
            "manual_measure": "Misura manuale",
            "confidence": "Affidabilit\u00e0",
        },
        "tendering": {
            "title": "Gara d\u2019appalto",
            "create_tender": "Crea gara d\u2019appalto",
            "bid": "Offerta",
            "award": "Aggiudicazione",
        },
        "modules": {
            "title": "Moduli",
            "installed": "Installati",
            "available": "Disponibili",
            "install": "Installa",
            "uninstall": "Disinstalla",
            "update": "Aggiorna",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "pz",
            "lsum": "a corpo",
            "h": "h",
            "set": "kit",
        },
    }

    # -------------------------------------------------------------------------
    # Dutch (Nederlands) — Begroting / RAW / STABU terminology
    # -------------------------------------------------------------------------
    nl: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Open-source bouwkostencalculatie",
        },
        "common": {
            "save": "Opslaan",
            "cancel": "Annuleren",
            "delete": "Verwijderen",
            "edit": "Bewerken",
            "create": "Aanmaken",
            "search": "Zoeken",
            "filter": "Filteren",
            "export": "Exporteren",
            "import": "Importeren",
            "loading": "Laden...",
            "error": "Fout",
            "success": "Gelukt",
            "confirm": "Bevestigen",
            "back": "Terug",
            "next": "Volgende",
            "yes": "Ja",
            "no": "Nee",
        },
        "auth": {
            "login": "Inloggen",
            "logout": "Uitloggen",
            "email": "E-mail",
            "password": "Wachtwoord",
        },
        "projects": {
            "title": "Projecten",
            "new_project": "Nieuw project",
            "project_name": "Projectnaam",
            "no_projects": "Nog geen projecten",
        },
        "boq": {
            "title": "Hoeveelhedenstaat",
            "position": "Post",
            "ordinal": "Volgnummer",
            "description": "Omschrijving",
            "quantity": "Hoeveelheid",
            "unit": "Eenheid",
            "unit_rate": "Eenheidsprijs",
            "total": "Totaal",
            "add_position": "Post toevoegen",
            "add_section": "Hoofdstuk toevoegen",
            "assembly": "Samengestelde prijs",
            "subtotal": "Subtotaal",
            "grand_total": "Eindtotaal",
        },
        "costs": {
            "title": "Prijsdatabase",
            "rate": "Prijs",
            "material": "Materiaal",
            "labor": "Arbeid",
            "equipment": "Materieel",
            "search_costs": "Prijzen zoeken...",
        },
        "validation": {
            "title": "Validatie",
            "passed": "Geslaagd",
            "warnings": "Waarschuwingen",
            "errors": "Fouten",
            "score": "Kwaliteitsscore",
            "run_validation": "Validatie starten",
            "missing_quantity": "Post {position} heeft geen hoeveelheid",
            "missing_rate": "Post {position} heeft geen eenheidsprijs",
            "missing_description": "Post {position} heeft geen omschrijving",
            "missing_classification": "Post {position} heeft een classificatiecode nodig",
            "duplicate_ordinal": "Dubbel volgnummer: {ordinal}",
            "rate_anomaly": "Eenheidsprijs {rate} overschrijdt drempelwaarde ({threshold})",
        },
        "cad": {
            "title": "CAD-import",
            "upload": "CAD-bestand uploaden",
            "supported_formats": "Ondersteund: DWG, DGN, RVT, IFC, PDF",
            "converting": "Converteren...",
            "elements_found": "{count} elementen gevonden",
        },
        "takeoff": {
            "title": "Hoeveelheden bepaling",
            "auto_detect": "Automatische detectie",
            "manual_measure": "Handmatige meting",
            "confidence": "Betrouwbaarheid",
        },
        "tendering": {
            "title": "Aanbesteding",
            "create_tender": "Aanbesteding aanmaken",
            "bid": "Inschrijving",
            "award": "Gunning",
        },
        "modules": {
            "title": "Modules",
            "installed": "Ge\u00efnstalleerd",
            "available": "Beschikbaar",
            "install": "Installeren",
            "uninstall": "De\u00efnstalleren",
            "update": "Bijwerken",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "st",
            "lsum": "post",
            "h": "uur",
            "set": "set",
        },
    }

    # -------------------------------------------------------------------------
    # Polish (Polski) — Kosztorys budowlany / KNR terminology
    # -------------------------------------------------------------------------
    pl: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Kosztorysowanie budowlane open-source",
        },
        "common": {
            "save": "Zapisz",
            "cancel": "Anuluj",
            "delete": "Usu\u0144",
            "edit": "Edytuj",
            "create": "Utw\u00f3rz",
            "search": "Szukaj",
            "filter": "Filtruj",
            "export": "Eksportuj",
            "import": "Importuj",
            "loading": "\u0141adowanie...",
            "error": "B\u0142\u0105d",
            "success": "Sukces",
            "confirm": "Potwierd\u017a",
            "back": "Wstecz",
            "next": "Dalej",
            "yes": "Tak",
            "no": "Nie",
        },
        "auth": {
            "login": "Zaloguj si\u0119",
            "logout": "Wyloguj si\u0119",
            "email": "E-mail",
            "password": "Has\u0142o",
        },
        "projects": {
            "title": "Projekty",
            "new_project": "Nowy projekt",
            "project_name": "Nazwa projektu",
            "no_projects": "Brak projekt\u00f3w",
        },
        "boq": {
            "title": "Kosztorys",
            "position": "Pozycja",
            "ordinal": "Numer porz\u0105dkowy",
            "description": "Opis",
            "quantity": "Ilo\u015b\u0107",
            "unit": "Jednostka",
            "unit_rate": "Cena jednostkowa",
            "total": "Razem",
            "add_position": "Dodaj pozycj\u0119",
            "add_section": "Dodaj dzia\u0142",
            "assembly": "Kalkulacja szczeg\u00f3\u0142owa",
            "subtotal": "Suma cz\u0119\u015bciowa",
            "grand_total": "Suma og\u00f3lna",
        },
        "costs": {
            "title": "Baza cenowa",
            "rate": "Cena",
            "material": "Materia\u0142",
            "labor": "Robocizna",
            "equipment": "Sprz\u0119t",
            "search_costs": "Szukaj cen...",
        },
        "validation": {
            "title": "Walidacja",
            "passed": "Zaliczone",
            "warnings": "Ostrze\u017cenia",
            "errors": "B\u0142\u0119dy",
            "score": "Ocena jako\u015bci",
            "run_validation": "Uruchom walidacj\u0119",
            "missing_quantity": "Pozycja {position} nie ma ilo\u015bci",
            "missing_rate": "Pozycja {position} nie ma ceny jednostkowej",
            "missing_description": "Pozycja {position} nie ma opisu",
            "missing_classification": "Pozycja {position} wymaga kodu klasyfikacji",
            "duplicate_ordinal": "Zduplikowany numer porz\u0105dkowy: {ordinal}",
            "rate_anomaly": "Cena jednostkowa {rate} przekracza pr\u00f3g ({threshold})",
        },
        "cad": {
            "title": "Import CAD",
            "upload": "Prze\u015blij plik CAD",
            "supported_formats": "Obs\u0142ugiwane: DWG, DGN, RVT, IFC, PDF",
            "converting": "Konwersja...",
            "elements_found": "Znaleziono element\u00f3w: {count}",
        },
        "takeoff": {
            "title": "Obmiar",
            "auto_detect": "Automatyczne wykrywanie",
            "manual_measure": "Pomiar r\u0119czny",
            "confidence": "Pewno\u015b\u0107",
        },
        "tendering": {
            "title": "Przetarg",
            "create_tender": "Utw\u00f3rz przetarg",
            "bid": "Oferta",
            "award": "Udzielenie zam\u00f3wienia",
        },
        "modules": {
            "title": "Modu\u0142y",
            "installed": "Zainstalowane",
            "available": "Dost\u0119pne",
            "install": "Zainstaluj",
            "uninstall": "Odinstaluj",
            "update": "Aktualizuj",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "szt",
            "lsum": "rycza\u0142t",
            "h": "godz",
            "set": "kpl",
        },
    }

    # -------------------------------------------------------------------------
    # Czech (\u010ce\u0161tina) — Rozpo\u010det stavby terminology
    # -------------------------------------------------------------------------
    cs: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Open-source rozpo\u010dtov\u00e1n\u00ed staveb",
        },
        "common": {
            "save": "Ulo\u017eit",
            "cancel": "Zru\u0161it",
            "delete": "Smazat",
            "edit": "Upravit",
            "create": "Vytvo\u0159it",
            "search": "Hledat",
            "filter": "Filtrovat",
            "export": "Exportovat",
            "import": "Importovat",
            "loading": "Na\u010d\u00edt\u00e1n\u00ed...",
            "error": "Chyba",
            "success": "\u00dasp\u011bch",
            "confirm": "Potvrdit",
            "back": "Zp\u011bt",
            "next": "Dal\u0161\u00ed",
            "yes": "Ano",
            "no": "Ne",
        },
        "auth": {
            "login": "P\u0159ihl\u00e1sit se",
            "logout": "Odhl\u00e1sit se",
            "email": "E-mail",
            "password": "Heslo",
        },
        "projects": {
            "title": "Projekty",
            "new_project": "Nov\u00fd projekt",
            "project_name": "N\u00e1zev projektu",
            "no_projects": "\u017d\u00e1dn\u00e9 projekty",
        },
        "boq": {
            "title": "V\u00fdkaz v\u00fdm\u011br",
            "position": "Polo\u017eka",
            "ordinal": "Po\u0159adov\u00e9 \u010d\u00edslo",
            "description": "Popis",
            "quantity": "Mno\u017estv\u00ed",
            "unit": "M\u011brn\u00e1 jednotka",
            "unit_rate": "Jednotkov\u00e1 cena",
            "total": "Celkem",
            "add_position": "P\u0159idat polo\u017eku",
            "add_section": "P\u0159idat odd\u00edl",
            "assembly": "Kalkulace polo\u017eky",
            "subtotal": "Mezisou\u010det",
            "grand_total": "Celkov\u00e1 suma",
        },
        "costs": {
            "title": "Cenov\u00e1 datab\u00e1ze",
            "rate": "Cena",
            "material": "Materi\u00e1l",
            "labor": "Pr\u00e1ce",
            "equipment": "Stroje",
            "search_costs": "Hledat ceny...",
        },
        "validation": {
            "title": "Validace",
            "passed": "Bez z\u00e1vad",
            "warnings": "Upozorn\u011bn\u00ed",
            "errors": "Chyby",
            "score": "Hodnocen\u00ed kvality",
            "run_validation": "Spustit validaci",
            "missing_quantity": "Polo\u017eka {position} nem\u00e1 mno\u017estv\u00ed",
            "missing_rate": "Polo\u017eka {position} nem\u00e1 jednotkovou cenu",
            "missing_description": "Polo\u017eka {position} nem\u00e1 popis",
            "missing_classification": "Polo\u017eka {position} pot\u0159ebuje klasifika\u010dn\u00ed k\u00f3d",
            "duplicate_ordinal": "Duplicitn\u00ed po\u0159adov\u00e9 \u010d\u00edslo: {ordinal}",
            "rate_anomaly": "Jednotkov\u00e1 cena {rate} p\u0159ekra\u010duje pr\u00e1h ({threshold})",
        },
        "cad": {
            "title": "Import CAD",
            "upload": "Nahr\u00e1t soubor CAD",
            "supported_formats": "Podporovan\u00e9: DWG, DGN, RVT, IFC, PDF",
            "converting": "P\u0159ev\u00e1d\u011bn\u00ed...",
            "elements_found": "Nalezeno prvk\u016f: {count}",
        },
        "takeoff": {
            "title": "V\u00fdkaz v\u00fdm\u011br",
            "auto_detect": "Automatick\u00e1 detekce",
            "manual_measure": "Ru\u010dn\u00ed m\u011b\u0159en\u00ed",
            "confidence": "Spolehlivost",
        },
        "tendering": {
            "title": "V\u00fdb\u011brov\u00e9 \u0159\u00edzen\u00ed",
            "create_tender": "Vytvo\u0159it v\u00fdb\u011brov\u00e9 \u0159\u00edzen\u00ed",
            "bid": "Nab\u00eddka",
            "award": "Zad\u00e1n\u00ed zak\u00e1zky",
        },
        "modules": {
            "title": "Moduly",
            "installed": "Nainstalov\u00e1no",
            "available": "Dostupn\u00e9",
            "install": "Nainstalovat",
            "uninstall": "Odinstalovat",
            "update": "Aktualizovat",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "ks",
            "lsum": "pau\u0161\u00e1l",
            "h": "hod",
            "set": "sada",
        },
    }

    # -------------------------------------------------------------------------
    # Turkish (T\u00fcrk\u00e7e) — Ke\u015fif / Metraj / \u0130hale terminology
    # -------------------------------------------------------------------------
    tr: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "A\u00e7\u0131k kaynak in\u015faat maliyet tahmini",
        },
        "common": {
            "save": "Kaydet",
            "cancel": "\u0130ptal",
            "delete": "Sil",
            "edit": "D\u00fczenle",
            "create": "Olu\u015ftur",
            "search": "Ara",
            "filter": "Filtrele",
            "export": "D\u0131\u015fa aktar",
            "import": "\u0130\u00e7e aktar",
            "loading": "Y\u00fckleniyor...",
            "error": "Hata",
            "success": "Ba\u015far\u0131l\u0131",
            "confirm": "Onayla",
            "back": "Geri",
            "next": "\u0130leri",
            "yes": "Evet",
            "no": "Hay\u0131r",
        },
        "auth": {
            "login": "Giri\u015f yap",
            "logout": "\u00c7\u0131k\u0131\u015f yap",
            "email": "E-posta",
            "password": "\u015eifre",
        },
        "projects": {
            "title": "Projeler",
            "new_project": "Yeni proje",
            "project_name": "Proje ad\u0131",
            "no_projects": "Hen\u00fcz proje yok",
        },
        "boq": {
            "title": "Ke\u015fif \u00d6zeti",
            "position": "Pozisyon",
            "ordinal": "S\u0131ra numaras\u0131",
            "description": "Tan\u0131m",
            "quantity": "Metraj",
            "unit": "Birim",
            "unit_rate": "Birim fiyat",
            "total": "Toplam",
            "add_position": "Pozisyon ekle",
            "add_section": "B\u00f6l\u00fcm ekle",
            "assembly": "Analiz",
            "subtotal": "Ara toplam",
            "grand_total": "Genel toplam",
        },
        "costs": {
            "title": "Fiyat veritaban\u0131",
            "rate": "Fiyat",
            "material": "Malzeme",
            "labor": "\u0130\u015f\u00e7ilik",
            "equipment": "Makine",
            "search_costs": "Fiyat ara...",
        },
        "validation": {
            "title": "Do\u011frulama",
            "passed": "Ba\u015far\u0131l\u0131",
            "warnings": "Uyar\u0131lar",
            "errors": "Hatalar",
            "score": "Kalite puan\u0131",
            "run_validation": "Do\u011frulama ba\u015flat",
            "missing_quantity": "Pozisyon {position} metraj\u0131 yok",
            "missing_rate": "Pozisyon {position} birim fiyat\u0131 yok",
            "missing_description": "Pozisyon {position} tan\u0131m\u0131 yok",
            "missing_classification": "Pozisyon {position} s\u0131n\u0131fland\u0131rma kodu gerekli",
            "duplicate_ordinal": "Yinelenen s\u0131ra numaras\u0131: {ordinal}",
            "rate_anomaly": "Birim fiyat {rate} e\u015fik de\u011feri a\u015f\u0131yor ({threshold})",
        },
        "cad": {
            "title": "CAD i\u00e7e aktarma",
            "upload": "CAD dosyas\u0131 y\u00fckle",
            "supported_formats": "Desteklenen: DWG, DGN, RVT, IFC, PDF",
            "converting": "D\u00f6n\u00fc\u015ft\u00fcr\u00fcl\u00fcyor...",
            "elements_found": "{count} eleman bulundu",
        },
        "takeoff": {
            "title": "Metraj",
            "auto_detect": "Otomatik alg\u0131lama",
            "manual_measure": "Manuel \u00f6l\u00e7\u00fcm",
            "confidence": "G\u00fcvenilirlik",
        },
        "tendering": {
            "title": "\u0130hale",
            "create_tender": "\u0130hale olu\u015ftur",
            "bid": "Teklif",
            "award": "\u0130hale karar\u0131",
        },
        "modules": {
            "title": "Mod\u00fcller",
            "installed": "Y\u00fckl\u00fc",
            "available": "Mevcut",
            "install": "Y\u00fckle",
            "uninstall": "Kald\u0131r",
            "update": "G\u00fcncelle",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "ad",
            "lsum": "g\u00f6t\u00fcr\u00fc",
            "h": "sa",
            "set": "tk",
        },
    }

    # -------------------------------------------------------------------------
    # Swedish (Svenska) — Kalkyl / M\u00e4ngdf\u00f6rteckning terminology
    # -------------------------------------------------------------------------
    sv: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Byggkalkylering med \u00f6ppen k\u00e4llkod",
        },
        "common": {
            "save": "Spara",
            "cancel": "Avbryt",
            "delete": "Radera",
            "edit": "Redigera",
            "create": "Skapa",
            "search": "S\u00f6k",
            "filter": "Filtrera",
            "export": "Exportera",
            "import": "Importera",
            "loading": "Laddar...",
            "error": "Fel",
            "success": "Klart",
            "confirm": "Bekr\u00e4fta",
            "back": "Tillbaka",
            "next": "N\u00e4sta",
            "yes": "Ja",
            "no": "Nej",
        },
        "auth": {
            "login": "Logga in",
            "logout": "Logga ut",
            "email": "E-post",
            "password": "L\u00f6senord",
        },
        "projects": {
            "title": "Projekt",
            "new_project": "Nytt projekt",
            "project_name": "Projektnamn",
            "no_projects": "Inga projekt \u00e4nnu",
        },
        "boq": {
            "title": "M\u00e4ngdf\u00f6rteckning",
            "position": "Post",
            "ordinal": "Positionsnummer",
            "description": "Beskrivning",
            "quantity": "M\u00e4ngd",
            "unit": "Enhet",
            "unit_rate": "\u00c0-pris",
            "total": "Summa",
            "add_position": "L\u00e4gg till post",
            "add_section": "L\u00e4gg till avsnitt",
            "assembly": "Kalkylsammansatt",
            "subtotal": "Delsumma",
            "grand_total": "Totalsumma",
        },
        "costs": {
            "title": "Prisdatabas",
            "rate": "Pris",
            "material": "Material",
            "labor": "Arbetskraft",
            "equipment": "Maskiner",
            "search_costs": "S\u00f6k priser...",
        },
        "validation": {
            "title": "Validering",
            "passed": "Godk\u00e4nd",
            "warnings": "Varningar",
            "errors": "Fel",
            "score": "Kvalitetspo\u00e4ng",
            "run_validation": "K\u00f6r validering",
            "missing_quantity": "Post {position} saknar m\u00e4ngd",
            "missing_rate": "Post {position} saknar \u00e0-pris",
            "missing_description": "Post {position} saknar beskrivning",
            "missing_classification": "Post {position} beh\u00f6ver en klassificeringskod",
            "duplicate_ordinal": "Dubblerat positionsnummer: {ordinal}",
            "rate_anomaly": "\u00c0-pris {rate} \u00f6verstiger gr\u00e4nsv\u00e4rde ({threshold})",
        },
        "cad": {
            "title": "CAD-import",
            "upload": "Ladda upp CAD-fil",
            "supported_formats": "St\u00f6ds: DWG, DGN, RVT, IFC, PDF",
            "converting": "Konverterar...",
            "elements_found": "{count} element hittade",
        },
        "takeoff": {
            "title": "M\u00e4ngdavtagning",
            "auto_detect": "Automatisk detektion",
            "manual_measure": "Manuell m\u00e4tning",
            "confidence": "S\u00e4kerhet",
        },
        "tendering": {
            "title": "Upphandling",
            "create_tender": "Skapa upphandling",
            "bid": "Anbud",
            "award": "Tilldelning",
        },
        "modules": {
            "title": "Moduler",
            "installed": "Installerade",
            "available": "Tillg\u00e4ngliga",
            "install": "Installera",
            "uninstall": "Avinstallera",
            "update": "Uppdatera",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "st",
            "lsum": "a-pris",
            "h": "tim",
            "set": "set",
        },
    }

    # -------------------------------------------------------------------------
    # Norwegian (Norsk) — Kalkyle / Mengdefortegnelse / NS 3420 terminology
    # -------------------------------------------------------------------------
    no: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Byggekalkyle med \u00e5pen kildekode",
        },
        "common": {
            "save": "Lagre",
            "cancel": "Avbryt",
            "delete": "Slett",
            "edit": "Rediger",
            "create": "Opprett",
            "search": "S\u00f8k",
            "filter": "Filtrer",
            "export": "Eksporter",
            "import": "Importer",
            "loading": "Laster...",
            "error": "Feil",
            "success": "Fullf\u00f8rt",
            "confirm": "Bekreft",
            "back": "Tilbake",
            "next": "Neste",
            "yes": "Ja",
            "no": "Nei",
        },
        "auth": {
            "login": "Logg inn",
            "logout": "Logg ut",
            "email": "E-post",
            "password": "Passord",
        },
        "projects": {
            "title": "Prosjekter",
            "new_project": "Nytt prosjekt",
            "project_name": "Prosjektnavn",
            "no_projects": "Ingen prosjekter enn\u00e5",
        },
        "boq": {
            "title": "Mengdefortegnelse",
            "position": "Post",
            "ordinal": "Posisjonsnummer",
            "description": "Beskrivelse",
            "quantity": "Mengde",
            "unit": "Enhet",
            "unit_rate": "Enhetspris",
            "total": "Sum",
            "add_position": "Legg til post",
            "add_section": "Legg til avsnitt",
            "assembly": "Sammensatt pris",
            "subtotal": "Delsum",
            "grand_total": "Totalsum",
        },
        "costs": {
            "title": "Prisdatabase",
            "rate": "Pris",
            "material": "Materiale",
            "labor": "Arbeidskraft",
            "equipment": "Maskin",
            "search_costs": "S\u00f8k etter priser...",
        },
        "validation": {
            "title": "Validering",
            "passed": "Godkjent",
            "warnings": "Advarsler",
            "errors": "Feil",
            "score": "Kvalitetspoeng",
            "run_validation": "Kj\u00f8r validering",
            "missing_quantity": "Post {position} mangler mengde",
            "missing_rate": "Post {position} mangler enhetspris",
            "missing_description": "Post {position} mangler beskrivelse",
            "missing_classification": "Post {position} trenger en klassifiseringskode",
            "duplicate_ordinal": "Duplikat posisjonsnummer: {ordinal}",
            "rate_anomaly": "Enhetspris {rate} overskrider terskel ({threshold})",
        },
        "cad": {
            "title": "CAD-import",
            "upload": "Last opp CAD-fil",
            "supported_formats": "St\u00f8ttet: DWG, DGN, RVT, IFC, PDF",
            "converting": "Konverterer...",
            "elements_found": "{count} elementer funnet",
        },
        "takeoff": {
            "title": "Mengdeberegning",
            "auto_detect": "Automatisk deteksjon",
            "manual_measure": "Manuell m\u00e5ling",
            "confidence": "P\u00e5litelighet",
        },
        "tendering": {
            "title": "Anbud",
            "create_tender": "Opprett anbud",
            "bid": "Tilbud",
            "award": "Tildeling",
        },
        "modules": {
            "title": "Moduler",
            "installed": "Installert",
            "available": "Tilgjengelig",
            "install": "Installer",
            "uninstall": "Avinstaller",
            "update": "Oppdater",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "stk",
            "lsum": "rund sum",
            "h": "t",
            "set": "sett",
        },
    }

    # -------------------------------------------------------------------------
    # Danish (Dansk) — Tilbudsliste / Byggekalkulation terminology
    # -------------------------------------------------------------------------
    da: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Byggekalkulation med \u00e5ben kildekode",
        },
        "common": {
            "save": "Gem",
            "cancel": "Annuller",
            "delete": "Slet",
            "edit": "Rediger",
            "create": "Opret",
            "search": "S\u00f8g",
            "filter": "Filtrer",
            "export": "Eksporter",
            "import": "Importer",
            "loading": "Indl\u00e6ser...",
            "error": "Fejl",
            "success": "Gennemf\u00f8rt",
            "confirm": "Bekr\u00e6ft",
            "back": "Tilbage",
            "next": "N\u00e6ste",
            "yes": "Ja",
            "no": "Nej",
        },
        "auth": {
            "login": "Log ind",
            "logout": "Log ud",
            "email": "E-mail",
            "password": "Adgangskode",
        },
        "projects": {
            "title": "Projekter",
            "new_project": "Nyt projekt",
            "project_name": "Projektnavn",
            "no_projects": "Ingen projekter endnu",
        },
        "boq": {
            "title": "Tilbudsliste",
            "position": "Post",
            "ordinal": "Positionsnummer",
            "description": "Beskrivelse",
            "quantity": "M\u00e6ngde",
            "unit": "Enhed",
            "unit_rate": "Enhedspris",
            "total": "I alt",
            "add_position": "Tilf\u00f8j post",
            "add_section": "Tilf\u00f8j afsnit",
            "assembly": "Sammensat pris",
            "subtotal": "Subtotal",
            "grand_total": "Total",
        },
        "costs": {
            "title": "Prisdatabase",
            "rate": "Pris",
            "material": "Materiale",
            "labor": "Arbejdskraft",
            "equipment": "Maskinel",
            "search_costs": "S\u00f8g efter priser...",
        },
        "validation": {
            "title": "Validering",
            "passed": "Best\u00e5et",
            "warnings": "Advarsler",
            "errors": "Fejl",
            "score": "Kvalitetspoint",
            "run_validation": "K\u00f8r validering",
            "missing_quantity": "Post {position} mangler m\u00e6ngde",
            "missing_rate": "Post {position} mangler enhedspris",
            "missing_description": "Post {position} mangler beskrivelse",
            "missing_classification": "Post {position} kr\u00e6ver en klassifikationskode",
            "duplicate_ordinal": "Duplikeret positionsnummer: {ordinal}",
            "rate_anomaly": "Enhedspris {rate} overskrider t\u00e6rskelv\u00e6rdi ({threshold})",
        },
        "cad": {
            "title": "CAD-import",
            "upload": "Upload CAD-fil",
            "supported_formats": "Underst\u00f8ttet: DWG, DGN, RVT, IFC, PDF",
            "converting": "Konverterer...",
            "elements_found": "{count} elementer fundet",
        },
        "takeoff": {
            "title": "M\u00e6ngdeberegning",
            "auto_detect": "Automatisk registrering",
            "manual_measure": "Manuel opm\u00e5ling",
            "confidence": "P\u00e5lidelighed",
        },
        "tendering": {
            "title": "Udbud",
            "create_tender": "Opret udbud",
            "bid": "Tilbud",
            "award": "Tildeling",
        },
        "modules": {
            "title": "Moduler",
            "installed": "Installeret",
            "available": "Tilg\u00e6ngelige",
            "install": "Installer",
            "uninstall": "Afinstaller",
            "update": "Opdater",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "stk",
            "lsum": "sum",
            "h": "t",
            "set": "s\u00e6t",
        },
    }

    # -------------------------------------------------------------------------
    # Finnish (Suomi) — Kustannuslaskenta / Talo 2000 terminology
    # -------------------------------------------------------------------------
    fi: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "Avoimen l\u00e4hdekoodin rakennuskustannuslaskenta",
        },
        "common": {
            "save": "Tallenna",
            "cancel": "Peruuta",
            "delete": "Poista",
            "edit": "Muokkaa",
            "create": "Luo",
            "search": "Hae",
            "filter": "Suodata",
            "export": "Vie",
            "import": "Tuo",
            "loading": "Ladataan...",
            "error": "Virhe",
            "success": "Onnistui",
            "confirm": "Vahvista",
            "back": "Takaisin",
            "next": "Seuraava",
            "yes": "Kyll\u00e4",
            "no": "Ei",
        },
        "auth": {
            "login": "Kirjaudu sis\u00e4\u00e4n",
            "logout": "Kirjaudu ulos",
            "email": "S\u00e4hk\u00f6posti",
            "password": "Salasana",
        },
        "projects": {
            "title": "Projektit",
            "new_project": "Uusi projekti",
            "project_name": "Projektin nimi",
            "no_projects": "Ei projekteja",
        },
        "boq": {
            "title": "M\u00e4\u00e4r\u00e4luettelo",
            "position": "Nimike",
            "ordinal": "J\u00e4rjestysnumero",
            "description": "Kuvaus",
            "quantity": "M\u00e4\u00e4r\u00e4",
            "unit": "Yksikk\u00f6",
            "unit_rate": "Yksikk\u00f6hinta",
            "total": "Yhteens\u00e4",
            "add_position": "Lis\u00e4\u00e4 nimike",
            "add_section": "Lis\u00e4\u00e4 osio",
            "assembly": "Rakenneosa",
            "subtotal": "V\u00e4lisumma",
            "grand_total": "Loppusumma",
        },
        "costs": {
            "title": "Hintatietokanta",
            "rate": "Hinta",
            "material": "Materiaali",
            "labor": "Ty\u00f6",
            "equipment": "Kalusto",
            "search_costs": "Hae hintoja...",
        },
        "validation": {
            "title": "Validointi",
            "passed": "Hyv\u00e4ksytty",
            "warnings": "Varoitukset",
            "errors": "Virheet",
            "score": "Laatupistem\u00e4\u00e4r\u00e4",
            "run_validation": "Suorita validointi",
            "missing_quantity": "Nimikkeelt\u00e4 {position} puuttuu m\u00e4\u00e4r\u00e4",
            "missing_rate": "Nimikkeelt\u00e4 {position} puuttuu yksikk\u00f6hinta",
            "missing_description": "Nimikkeelt\u00e4 {position} puuttuu kuvaus",
            "missing_classification": "Nimike {position} tarvitsee luokituskoodin",
            "duplicate_ordinal": "J\u00e4rjestysnumeron kaksoiskappale: {ordinal}",
            "rate_anomaly": "Yksikk\u00f6hinta {rate} ylitt\u00e4\u00e4 kynnysarvon ({threshold})",
        },
        "cad": {
            "title": "CAD-tuonti",
            "upload": "Lataa CAD-tiedosto",
            "supported_formats": "Tuetut: DWG, DGN, RVT, IFC, PDF",
            "converting": "Muunnetaan...",
            "elements_found": "{count} elementti\u00e4 l\u00f6ytyi",
        },
        "takeoff": {
            "title": "M\u00e4\u00e4r\u00e4laskenta",
            "auto_detect": "Automaattinen tunnistus",
            "manual_measure": "Manuaalinen mittaus",
            "confidence": "Luotettavuus",
        },
        "tendering": {
            "title": "Tarjouskilpailu",
            "create_tender": "Luo tarjouskilpailu",
            "bid": "Tarjous",
            "award": "Hankintap\u00e4\u00e4t\u00f6s",
        },
        "modules": {
            "title": "Moduulit",
            "installed": "Asennettu",
            "available": "Saatavilla",
            "install": "Asenna",
            "uninstall": "Poista asennus",
            "update": "P\u00e4ivit\u00e4",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "kpl",
            "lsum": "er\u00e4",
            "h": "h",
            "set": "sarja",
        },
    }

    # -------------------------------------------------------------------------
    # Arabic (\u0627\u0644\u0639\u0631\u0628\u064a\u0629) — \u062a\u0642\u062f\u064a\u0631 \u0627\u0644\u062a\u0643\u0627\u0644\u064a\u0641 / \u062c\u062f\u0648\u0644 \u0627\u0644\u0643\u0645\u064a\u0627\u062a terminology
    # -------------------------------------------------------------------------
    ar: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "\u062a\u0642\u062f\u064a\u0631 \u062a\u0643\u0627\u0644\u064a\u0641 \u0627\u0644\u0628\u0646\u0627\u0621 \u0645\u0641\u062a\u0648\u062d \u0627\u0644\u0645\u0635\u062f\u0631",
        },
        "common": {
            "save": "\u062d\u0641\u0638",
            "cancel": "\u0625\u0644\u063a\u0627\u0621",
            "delete": "\u062d\u0630\u0641",
            "edit": "\u062a\u0639\u062f\u064a\u0644",
            "create": "\u0625\u0646\u0634\u0627\u0621",
            "search": "\u0628\u062d\u062b",
            "filter": "\u062a\u0635\u0641\u064a\u0629",
            "export": "\u062a\u0635\u062f\u064a\u0631",
            "import": "\u0627\u0633\u062a\u064a\u0631\u0627\u062f",
            "loading": "\u062c\u0627\u0631\u064d \u0627\u0644\u062a\u062d\u0645\u064a\u0644...",
            "error": "\u062e\u0637\u0623",
            "success": "\u062a\u0645 \u0628\u0646\u062c\u0627\u062d",
            "confirm": "\u062a\u0623\u0643\u064a\u062f",
            "back": "\u0631\u062c\u0648\u0639",
            "next": "\u0627\u0644\u062a\u0627\u0644\u064a",
            "yes": "\u0646\u0639\u0645",
            "no": "\u0644\u0627",
        },
        "auth": {
            "login": "\u062a\u0633\u062c\u064a\u0644 \u0627\u0644\u062f\u062e\u0648\u0644",
            "logout": "\u062a\u0633\u062c\u064a\u0644 \u0627\u0644\u062e\u0631\u0648\u062c",
            "email": "\u0627\u0644\u0628\u0631\u064a\u062f \u0627\u0644\u0625\u0644\u0643\u062a\u0631\u0648\u0646\u064a",
            "password": "\u0643\u0644\u0645\u0629 \u0627\u0644\u0645\u0631\u0648\u0631",
        },
        "projects": {
            "title": "\u0627\u0644\u0645\u0634\u0627\u0631\u064a\u0639",
            "new_project": "\u0645\u0634\u0631\u0648\u0639 \u062c\u062f\u064a\u062f",
            "project_name": "\u0627\u0633\u0645 \u0627\u0644\u0645\u0634\u0631\u0648\u0639",
            "no_projects": "\u0644\u0627 \u062a\u0648\u062c\u062f \u0645\u0634\u0627\u0631\u064a\u0639 \u0628\u0639\u062f",
        },
        "boq": {
            "title": "\u062c\u062f\u0648\u0644 \u0627\u0644\u0643\u0645\u064a\u0627\u062a",
            "position": "\u0628\u0646\u062f",
            "ordinal": "\u0631\u0642\u0645 \u0627\u0644\u062a\u0633\u0644\u0633\u0644",
            "description": "\u0627\u0644\u0648\u0635\u0641",
            "quantity": "\u0627\u0644\u0643\u0645\u064a\u0629",
            "unit": "\u0627\u0644\u0648\u062d\u062f\u0629",
            "unit_rate": "\u0633\u0639\u0631 \u0627\u0644\u0648\u062d\u062f\u0629",
            "total": "\u0627\u0644\u0625\u062c\u0645\u0627\u0644\u064a",
            "add_position": "\u0625\u0636\u0627\u0641\u0629 \u0628\u0646\u062f",
            "add_section": "\u0625\u0636\u0627\u0641\u0629 \u0642\u0633\u0645",
            "assembly": "\u062a\u062d\u0644\u064a\u0644 \u0633\u0639\u0631",
            "subtotal": "\u0627\u0644\u0645\u062c\u0645\u0648\u0639 \u0627\u0644\u0641\u0631\u0639\u064a",
            "grand_total": "\u0627\u0644\u0645\u062c\u0645\u0648\u0639 \u0627\u0644\u0643\u0644\u064a",
        },
        "costs": {
            "title": "\u0642\u0627\u0639\u062f\u0629 \u0628\u064a\u0627\u0646\u0627\u062a \u0627\u0644\u0623\u0633\u0639\u0627\u0631",
            "rate": "\u0627\u0644\u0633\u0639\u0631",
            "material": "\u0645\u0648\u0627\u062f",
            "labor": "\u0639\u0645\u0627\u0644\u0629",
            "equipment": "\u0645\u0639\u062f\u0627\u062a",
            "search_costs": "\u0628\u062d\u062b \u0641\u064a \u0627\u0644\u0623\u0633\u0639\u0627\u0631...",
        },
        "validation": {
            "title": "\u0627\u0644\u062a\u062d\u0642\u0642",
            "passed": "\u0646\u0627\u062c\u062d",
            "warnings": "\u062a\u062d\u0630\u064a\u0631\u0627\u062a",
            "errors": "\u0623\u062e\u0637\u0627\u0621",
            "score": "\u062f\u0631\u062c\u0629 \u0627\u0644\u062c\u0648\u062f\u0629",
            "run_validation": "\u062a\u0634\u063a\u064a\u0644 \u0627\u0644\u062a\u062d\u0642\u0642",
            "missing_quantity": "\u0627\u0644\u0628\u0646\u062f {position} \u0628\u062f\u0648\u0646 \u0643\u0645\u064a\u0629",
            "missing_rate": "\u0627\u0644\u0628\u0646\u062f {position} \u0628\u062f\u0648\u0646 \u0633\u0639\u0631 \u0648\u062d\u062f\u0629",
            "missing_description": "\u0627\u0644\u0628\u0646\u062f {position} \u0628\u062f\u0648\u0646 \u0648\u0635\u0641",
            "missing_classification": "\u0627\u0644\u0628\u0646\u062f {position} \u064a\u062d\u062a\u0627\u062c \u0631\u0645\u0632 \u062a\u0635\u0646\u064a\u0641",
            "duplicate_ordinal": "\u0631\u0642\u0645 \u062a\u0633\u0644\u0633\u0644 \u0645\u0643\u0631\u0631: {ordinal}",
            "rate_anomaly": "\u0633\u0639\u0631 \u0627\u0644\u0648\u062d\u062f\u0629 {rate} \u064a\u062a\u062c\u0627\u0648\u0632 \u0627\u0644\u062d\u062f ({threshold})",
        },
        "cad": {
            "title": "\u0627\u0633\u062a\u064a\u0631\u0627\u062f CAD",
            "upload": "\u0631\u0641\u0639 \u0645\u0644\u0641 CAD",
            "supported_formats": "\u0627\u0644\u0635\u064a\u063a: DWG\u060c DGN\u060c RVT\u060c IFC\u060c PDF",
            "converting": "\u062c\u0627\u0631\u064d \u0627\u0644\u062a\u062d\u0648\u064a\u0644...",
            "elements_found": "\u062a\u0645 \u0627\u0644\u0639\u062b\u0648\u0631 \u0639\u0644\u0649 {count} \u0639\u0646\u0635\u0631",
        },
        "takeoff": {
            "title": "\u062d\u0635\u0631 \u0627\u0644\u0643\u0645\u064a\u0627\u062a",
            "auto_detect": "\u0643\u0634\u0641 \u062a\u0644\u0642\u0627\u0626\u064a",
            "manual_measure": "\u0642\u064a\u0627\u0633 \u064a\u062f\u0648\u064a",
            "confidence": "\u0627\u0644\u0645\u0648\u062b\u0648\u0642\u064a\u0629",
        },
        "tendering": {
            "title": "\u0627\u0644\u0645\u0646\u0627\u0642\u0635\u0627\u062a",
            "create_tender": "\u0625\u0646\u0634\u0627\u0621 \u0645\u0646\u0627\u0642\u0635\u0629",
            "bid": "\u0639\u0631\u0636 \u0633\u0639\u0631",
            "award": "\u062a\u0631\u0633\u064a\u0629",
        },
        "modules": {
            "title": "\u0627\u0644\u0648\u062d\u062f\u0627\u062a",
            "installed": "\u0645\u064f\u062b\u0628\u0651\u062a",
            "available": "\u0645\u062a\u0627\u062d",
            "install": "\u062a\u062b\u0628\u064a\u062a",
            "uninstall": "\u0625\u0632\u0627\u0644\u0629",
            "update": "\u062a\u062d\u062f\u064a\u062b",
        },
        "units": {
            "m": "\u0645",
            "m2": "\u0645\u00b2",
            "m3": "\u0645\u00b3",
            "kg": "\u0643\u063a",
            "t": "\u0637\u0646",
            "pcs": "\u0642\u0637\u0639\u0629",
            "lsum": "\u0645\u0642\u0637\u0648\u0639\u064a\u0629",
            "h": "\u0633\u0627\u0639\u0629",
            "set": "\u0637\u0642\u0645",
        },
    }

    # -------------------------------------------------------------------------
    # Chinese Simplified (\u7b80\u4f53\u4e2d\u6587) — \u5de5\u7a0b\u9020\u4ef7 / \u5de5\u7a0b\u91cf\u6e05\u5355 terminology
    # -------------------------------------------------------------------------
    zh: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "\u5f00\u6e90\u5efa\u7b51\u5de5\u7a0b\u9020\u4ef7",
        },
        "common": {
            "save": "\u4fdd\u5b58",
            "cancel": "\u53d6\u6d88",
            "delete": "\u5220\u9664",
            "edit": "\u7f16\u8f91",
            "create": "\u521b\u5efa",
            "search": "\u641c\u7d22",
            "filter": "\u7b5b\u9009",
            "export": "\u5bfc\u51fa",
            "import": "\u5bfc\u5165",
            "loading": "\u52a0\u8f7d\u4e2d...",
            "error": "\u9519\u8bef",
            "success": "\u6210\u529f",
            "confirm": "\u786e\u8ba4",
            "back": "\u8fd4\u56de",
            "next": "\u4e0b\u4e00\u6b65",
            "yes": "\u662f",
            "no": "\u5426",
        },
        "auth": {
            "login": "\u767b\u5f55",
            "logout": "\u9000\u51fa",
            "email": "\u7535\u5b50\u90ae\u7bb1",
            "password": "\u5bc6\u7801",
        },
        "projects": {
            "title": "\u9879\u76ee",
            "new_project": "\u65b0\u5efa\u9879\u76ee",
            "project_name": "\u9879\u76ee\u540d\u79f0",
            "no_projects": "\u6682\u65e0\u9879\u76ee",
        },
        "boq": {
            "title": "\u5de5\u7a0b\u91cf\u6e05\u5355",
            "position": "\u6e05\u5355\u9879",
            "ordinal": "\u5e8f\u53f7",
            "description": "\u9879\u76ee\u7279\u5f81\u63cf\u8ff0",
            "quantity": "\u5de5\u7a0b\u91cf",
            "unit": "\u8ba1\u91cf\u5355\u4f4d",
            "unit_rate": "\u7efc\u5408\u5355\u4ef7",
            "total": "\u5408\u8ba1",
            "add_position": "\u6dfb\u52a0\u6e05\u5355\u9879",
            "add_section": "\u6dfb\u52a0\u5206\u90e8",
            "assembly": "\u7ec4\u4ef7",
            "subtotal": "\u5c0f\u8ba1",
            "grand_total": "\u603b\u8ba1",
        },
        "costs": {
            "title": "\u4ef7\u683c\u6570\u636e\u5e93",
            "rate": "\u5355\u4ef7",
            "material": "\u6750\u6599",
            "labor": "\u4eba\u5de5",
            "equipment": "\u673a\u68b0",
            "search_costs": "\u641c\u7d22\u4ef7\u683c...",
        },
        "validation": {
            "title": "\u6821\u9a8c",
            "passed": "\u901a\u8fc7",
            "warnings": "\u8b66\u544a",
            "errors": "\u9519\u8bef",
            "score": "\u8d28\u91cf\u8bc4\u5206",
            "run_validation": "\u8fd0\u884c\u6821\u9a8c",
            "missing_quantity": "\u6e05\u5355\u9879 {position} \u7f3a\u5c11\u5de5\u7a0b\u91cf",
            "missing_rate": "\u6e05\u5355\u9879 {position} \u7f3a\u5c11\u7efc\u5408\u5355\u4ef7",
            "missing_description": "\u6e05\u5355\u9879 {position} \u7f3a\u5c11\u63cf\u8ff0",
            "missing_classification": "\u6e05\u5355\u9879 {position} \u9700\u8981\u5206\u7c7b\u7f16\u7801",
            "duplicate_ordinal": "\u5e8f\u53f7\u91cd\u590d\uff1a{ordinal}",
            "rate_anomaly": "\u7efc\u5408\u5355\u4ef7 {rate} \u8d85\u51fa\u9608\u503c ({threshold})",
        },
        "cad": {
            "title": "CAD \u5bfc\u5165",
            "upload": "\u4e0a\u4f20 CAD \u6587\u4ef6",
            "supported_formats": "\u652f\u6301\u683c\u5f0f\uff1aDWG\u3001DGN\u3001RVT\u3001IFC\u3001PDF",
            "converting": "\u8f6c\u6362\u4e2d...",
            "elements_found": "\u53d1\u73b0 {count} \u4e2a\u6784\u4ef6",
        },
        "takeoff": {
            "title": "\u5de5\u7a0b\u91cf\u8ba1\u7b97",
            "auto_detect": "\u81ea\u52a8\u8bc6\u522b",
            "manual_measure": "\u624b\u52a8\u6d4b\u91cf",
            "confidence": "\u7f6e\u4fe1\u5ea6",
        },
        "tendering": {
            "title": "\u62db\u6807\u6295\u6807",
            "create_tender": "\u521b\u5efa\u62db\u6807",
            "bid": "\u6295\u6807",
            "award": "\u4e2d\u6807",
        },
        "modules": {
            "title": "\u6a21\u5757",
            "installed": "\u5df2\u5b89\u88c5",
            "available": "\u53ef\u7528",
            "install": "\u5b89\u88c5",
            "uninstall": "\u5378\u8f7d",
            "update": "\u66f4\u65b0",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "\u4e2a",
            "lsum": "\u9879",
            "h": "\u5de5\u65e5",
            "set": "\u5957",
        },
    }

    # -------------------------------------------------------------------------
    # Japanese (\u65e5\u672c\u8a9e) — \u7a4d\u7b97 / \u898b\u7a4d / \u6570\u91cf\u8abf\u66f8 terminology
    # -------------------------------------------------------------------------
    ja: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "\u30aa\u30fc\u30d7\u30f3\u30bd\u30fc\u30b9\u5efa\u8a2d\u30b3\u30b9\u30c8\u898b\u7a4d",
        },
        "common": {
            "save": "\u4fdd\u5b58",
            "cancel": "\u30ad\u30e3\u30f3\u30bb\u30eb",
            "delete": "\u524a\u9664",
            "edit": "\u7de8\u96c6",
            "create": "\u4f5c\u6210",
            "search": "\u691c\u7d22",
            "filter": "\u30d5\u30a3\u30eb\u30bf\u30fc",
            "export": "\u30a8\u30af\u30b9\u30dd\u30fc\u30c8",
            "import": "\u30a4\u30f3\u30dd\u30fc\u30c8",
            "loading": "\u8aad\u307f\u8fbc\u307f\u4e2d...",
            "error": "\u30a8\u30e9\u30fc",
            "success": "\u6210\u529f",
            "confirm": "\u78ba\u8a8d",
            "back": "\u623b\u308b",
            "next": "\u6b21\u3078",
            "yes": "\u306f\u3044",
            "no": "\u3044\u3044\u3048",
        },
        "auth": {
            "login": "\u30ed\u30b0\u30a4\u30f3",
            "logout": "\u30ed\u30b0\u30a2\u30a6\u30c8",
            "email": "\u30e1\u30fc\u30eb\u30a2\u30c9\u30ec\u30b9",
            "password": "\u30d1\u30b9\u30ef\u30fc\u30c9",
        },
        "projects": {
            "title": "\u30d7\u30ed\u30b8\u30a7\u30af\u30c8",
            "new_project": "\u65b0\u898f\u30d7\u30ed\u30b8\u30a7\u30af\u30c8",
            "project_name": "\u30d7\u30ed\u30b8\u30a7\u30af\u30c8\u540d",
            "no_projects": "\u30d7\u30ed\u30b8\u30a7\u30af\u30c8\u306a\u3057",
        },
        "boq": {
            "title": "\u6570\u91cf\u8abf\u66f8",
            "position": "\u9805\u76ee",
            "ordinal": "\u756a\u53f7",
            "description": "\u540d\u79f0\u30fb\u4ed5\u69d8",
            "quantity": "\u6570\u91cf",
            "unit": "\u5358\u4f4d",
            "unit_rate": "\u5358\u4fa1",
            "total": "\u91d1\u984d",
            "add_position": "\u9805\u76ee\u3092\u8ffd\u52a0",
            "add_section": "\u30bb\u30af\u30b7\u30e7\u30f3\u3092\u8ffd\u52a0",
            "assembly": "\u8907\u5408\u5358\u4fa1",
            "subtotal": "\u5c0f\u8a08",
            "grand_total": "\u5408\u8a08",
        },
        "costs": {
            "title": "\u5358\u4fa1\u30c7\u30fc\u30bf\u30d9\u30fc\u30b9",
            "rate": "\u5358\u4fa1",
            "material": "\u6750\u6599",
            "labor": "\u52b4\u52d9",
            "equipment": "\u6a5f\u68b0",
            "search_costs": "\u5358\u4fa1\u3092\u691c\u7d22...",
        },
        "validation": {
            "title": "\u691c\u8a3c",
            "passed": "\u5408\u683c",
            "warnings": "\u8b66\u544a",
            "errors": "\u30a8\u30e9\u30fc",
            "score": "\u54c1\u8cea\u30b9\u30b3\u30a2",
            "run_validation": "\u691c\u8a3c\u3092\u5b9f\u884c",
            "missing_quantity": "\u9805\u76ee {position} \u306b\u6570\u91cf\u304c\u3042\u308a\u307e\u305b\u3093",
            "missing_rate": "\u9805\u76ee {position} \u306b\u5358\u4fa1\u304c\u3042\u308a\u307e\u305b\u3093",
            "missing_description": "\u9805\u76ee {position} \u306b\u540d\u79f0\u304c\u3042\u308a\u307e\u305b\u3093",
            "missing_classification": "\u9805\u76ee {position} \u306b\u5206\u985e\u30b3\u30fc\u30c9\u304c\u5fc5\u8981\u3067\u3059",
            "duplicate_ordinal": "\u756a\u53f7\u304c\u91cd\u8907\u3057\u3066\u3044\u307e\u3059: {ordinal}",
            "rate_anomaly": "\u5358\u4fa1 {rate} \u304c\u3057\u304d\u3044\u5024\u3092\u8d85\u904e ({threshold})",
        },
        "cad": {
            "title": "CAD \u30a4\u30f3\u30dd\u30fc\u30c8",
            "upload": "CAD \u30d5\u30a1\u30a4\u30eb\u3092\u30a2\u30c3\u30d7\u30ed\u30fc\u30c9",
            "supported_formats": "\u5bfe\u5fdc\u5f62\u5f0f: DWG, DGN, RVT, IFC, PDF",
            "converting": "\u5909\u63db\u4e2d...",
            "elements_found": "{count} \u500b\u306e\u8981\u7d20\u3092\u691c\u51fa",
        },
        "takeoff": {
            "title": "\u62fe\u3044\u51fa\u3057",
            "auto_detect": "\u81ea\u52d5\u691c\u51fa",
            "manual_measure": "\u624b\u52d5\u8a08\u6e2c",
            "confidence": "\u4fe1\u983c\u5ea6",
        },
        "tendering": {
            "title": "\u5165\u672d",
            "create_tender": "\u5165\u672d\u3092\u4f5c\u6210",
            "bid": "\u898b\u7a4d",
            "award": "\u843d\u672d",
        },
        "modules": {
            "title": "\u30e2\u30b8\u30e5\u30fc\u30eb",
            "installed": "\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb\u6e08\u307f",
            "available": "\u5229\u7528\u53ef\u80fd",
            "install": "\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb",
            "uninstall": "\u30a2\u30f3\u30a4\u30f3\u30b9\u30c8\u30fc\u30eb",
            "update": "\u66f4\u65b0",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "\u500b",
            "lsum": "\u4e00\u5f0f",
            "h": "\u4eba\u5de5",
            "set": "\u30bb\u30c3\u30c8",
        },
    }

    # -------------------------------------------------------------------------
    # Korean (\ud55c\uad6d\uc5b4) — \uac74\uc124 \uc801\uc0b0 / \ubb3c\ub7c9\uc0b0\ucd9c\uc11c terminology
    # -------------------------------------------------------------------------
    ko: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "\uc624\ud508\uc18c\uc2a4 \uac74\uc124 \uc6d0\uac00 \uc0b0\uc815",
        },
        "common": {
            "save": "\uc800\uc7a5",
            "cancel": "\ucde8\uc18c",
            "delete": "\uc0ad\uc81c",
            "edit": "\ud3b8\uc9d1",
            "create": "\uc0dd\uc131",
            "search": "\uac80\uc0c9",
            "filter": "\ud544\ud130",
            "export": "\ub0b4\ubcf4\ub0b4\uae30",
            "import": "\uac00\uc838\uc624\uae30",
            "loading": "\ub85c\ub529 \uc911...",
            "error": "\uc624\ub958",
            "success": "\uc131\uacf5",
            "confirm": "\ud655\uc778",
            "back": "\ub4a4\ub85c",
            "next": "\ub2e4\uc74c",
            "yes": "\uc608",
            "no": "\uc544\ub2c8\uc624",
        },
        "auth": {
            "login": "\ub85c\uadf8\uc778",
            "logout": "\ub85c\uadf8\uc544\uc6c3",
            "email": "\uc774\uba54\uc77c",
            "password": "\ube44\ubc00\ubc88\ud638",
        },
        "projects": {
            "title": "\ud504\ub85c\uc81d\ud2b8",
            "new_project": "\uc0c8 \ud504\ub85c\uc81d\ud2b8",
            "project_name": "\ud504\ub85c\uc81d\ud2b8\uba85",
            "no_projects": "\ud504\ub85c\uc81d\ud2b8\uac00 \uc5c6\uc2b5\ub2c8\ub2e4",
        },
        "boq": {
            "title": "\ubb3c\ub7c9\uc0b0\ucd9c\uc11c",
            "position": "\ud56d\ubaa9",
            "ordinal": "\uc21c\ubc88",
            "description": "\uacf5\uc885\uba85",
            "quantity": "\uc218\ub7c9",
            "unit": "\ub2e8\uc704",
            "unit_rate": "\ub2e8\uac00",
            "total": "\uae08\uc561",
            "add_position": "\ud56d\ubaa9 \ucd94\uac00",
            "add_section": "\ubd80\ubb38 \ucd94\uac00",
            "assembly": "\uc77c\uc704\ub300\uac00",
            "subtotal": "\uc18c\uacc4",
            "grand_total": "\ucd1d\uacc4",
        },
        "costs": {
            "title": "\ub2e8\uac00 \ub370\uc774\ud130\ubca0\uc774\uc2a4",
            "rate": "\ub2e8\uac00",
            "material": "\uc7ac\ub8cc\ube44",
            "labor": "\ub178\ubb34\ube44",
            "equipment": "\uacbd\ube44",
            "search_costs": "\ub2e8\uac00 \uac80\uc0c9...",
        },
        "validation": {
            "title": "\uac80\uc99d",
            "passed": "\ud1b5\uacfc",
            "warnings": "\uacbd\uace0",
            "errors": "\uc624\ub958",
            "score": "\ud488\uc9c8 \uc810\uc218",
            "run_validation": "\uac80\uc99d \uc2e4\ud589",
            "missing_quantity": "\ud56d\ubaa9 {position}\uc5d0 \uc218\ub7c9\uc774 \uc5c6\uc2b5\ub2c8\ub2e4",
            "missing_rate": "\ud56d\ubaa9 {position}\uc5d0 \ub2e8\uac00\uac00 \uc5c6\uc2b5\ub2c8\ub2e4",
            "missing_description": "\ud56d\ubaa9 {position}\uc5d0 \uc124\uba85\uc774 \uc5c6\uc2b5\ub2c8\ub2e4",
            "missing_classification": "\ud56d\ubaa9 {position}\uc5d0 \ubd84\ub958 \ucf54\ub4dc\uac00 \ud544\uc694\ud569\ub2c8\ub2e4",
            "duplicate_ordinal": "\uc21c\ubc88 \uc911\ubcf5: {ordinal}",
            "rate_anomaly": "\ub2e8\uac00 {rate}\uc774(\uac00) \uc784\uacc4\uac12\uc744 \ucd08\uacfc ({threshold})",
        },
        "cad": {
            "title": "CAD \uac00\uc838\uc624\uae30",
            "upload": "CAD \ud30c\uc77c \uc5c5\ub85c\ub4dc",
            "supported_formats": "\uc9c0\uc6d0 \ud615\uc2dd: DWG, DGN, RVT, IFC, PDF",
            "converting": "\ubcc0\ud658 \uc911...",
            "elements_found": "{count}\uac1c \uc694\uc18c \ubc1c\uacac",
        },
        "takeoff": {
            "title": "\ubb3c\ub7c9 \uc0b0\ucd9c",
            "auto_detect": "\uc790\ub3d9 \uac10\uc9c0",
            "manual_measure": "\uc218\ub3d9 \uce21\uc815",
            "confidence": "\uc2e0\ub8b0\ub3c4",
        },
        "tendering": {
            "title": "\uc785\ucc30",
            "create_tender": "\uc785\ucc30 \uc0dd\uc131",
            "bid": "\ud22c\ucc30",
            "award": "\ub099\ucc30",
        },
        "modules": {
            "title": "\ubaa8\ub4c8",
            "installed": "\uc124\uce58\ub428",
            "available": "\uc0ac\uc6a9 \uac00\ub2a5",
            "install": "\uc124\uce58",
            "uninstall": "\uc81c\uac70",
            "update": "\uc5c5\ub370\uc774\ud2b8",
        },
        "units": {
            "m": "m",
            "m2": "m\u00b2",
            "m3": "m\u00b3",
            "kg": "kg",
            "t": "t",
            "pcs": "\uac1c",
            "lsum": "\uc2dd",
            "h": "\uc778",
            "set": "\uc138\ud2b8",
        },
    }

    # -------------------------------------------------------------------------
    # Hindi (\u0939\u093f\u0928\u094d\u0926\u0940) — \u0928\u093f\u0930\u094d\u092e\u093e\u0923 \u0932\u093e\u0917\u0924 \u0905\u0928\u0941\u092e\u093e\u0928 terminology
    # -------------------------------------------------------------------------
    hi: dict[str, dict[str, str]] = {
        "app": {
            "name": "OpenEstimate",
            "tagline": "\u0913\u092a\u0928 \u0938\u094b\u0930\u094d\u0938 \u0928\u093f\u0930\u094d\u092e\u093e\u0923 \u0932\u093e\u0917\u0924 \u0905\u0928\u0941\u092e\u093e\u0928",
        },
        "common": {
            "save": "\u0938\u0939\u0947\u091c\u0947\u0902",
            "cancel": "\u0930\u0926\u094d\u0926 \u0915\u0930\u0947\u0902",
            "delete": "\u0939\u091f\u093e\u090f\u0902",
            "edit": "\u0938\u0902\u092a\u093e\u0926\u093f\u0924 \u0915\u0930\u0947\u0902",
            "create": "\u092c\u0928\u093e\u090f\u0902",
            "search": "\u0916\u094b\u091c\u0947\u0902",
            "filter": "\u091b\u093e\u0928\u0947\u0902",
            "export": "\u0928\u093f\u0930\u094d\u092f\u093e\u0924 \u0915\u0930\u0947\u0902",
            "import": "\u0906\u092f\u093e\u0924 \u0915\u0930\u0947\u0902",
            "loading": "\u0932\u094b\u0921 \u0939\u094b \u0930\u0939\u093e \u0939\u0948...",
            "error": "\u0924\u094d\u0930\u0941\u091f\u093f",
            "success": "\u0938\u092b\u0932",
            "confirm": "\u092a\u0941\u0937\u094d\u091f\u093f \u0915\u0930\u0947\u0902",
            "back": "\u0935\u093e\u092a\u0938",
            "next": "\u0905\u0917\u0932\u093e",
            "yes": "\u0939\u093e\u0901",
            "no": "\u0928\u0939\u0940\u0902",
        },
        "auth": {
            "login": "\u0932\u0949\u0917 \u0907\u0928",
            "logout": "\u0932\u0949\u0917 \u0906\u0909\u091f",
            "email": "\u0908\u092e\u0947\u0932",
            "password": "\u092a\u093e\u0938\u0935\u0930\u094d\u0921",
        },
        "projects": {
            "title": "\u092a\u0930\u093f\u092f\u094b\u091c\u0928\u093e\u090f\u0902",
            "new_project": "\u0928\u0908 \u092a\u0930\u093f\u092f\u094b\u091c\u0928\u093e",
            "project_name": "\u092a\u0930\u093f\u092f\u094b\u091c\u0928\u093e \u0915\u093e \u0928\u093e\u092e",
            "no_projects": "\u0905\u092d\u0940 \u0915\u094b\u0908 \u092a\u0930\u093f\u092f\u094b\u091c\u0928\u093e \u0928\u0939\u0940\u0902",
        },
        "boq": {
            "title": "\u092e\u093e\u0924\u094d\u0930\u093e \u0935\u093f\u0935\u0930\u0923",
            "position": "\u092e\u0926",
            "ordinal": "\u0915\u094d\u0930\u092e \u0938\u0902\u0916\u094d\u092f\u093e",
            "description": "\u0935\u093f\u0935\u0930\u0923",
            "quantity": "\u092e\u093e\u0924\u094d\u0930\u093e",
            "unit": "\u0907\u0915\u093e\u0908",
            "unit_rate": "\u0926\u0930",
            "total": "\u0915\u0941\u0932",
            "add_position": "\u092e\u0926 \u091c\u094b\u0921\u093c\u0947\u0902",
            "add_section": "\u0905\u0928\u0941\u092d\u093e\u0917 \u091c\u094b\u0921\u093c\u0947\u0902",
            "assembly": "\u0938\u0902\u092f\u094b\u091c\u093f\u0924 \u0926\u0930",
            "subtotal": "\u0909\u092a-\u092f\u094b\u0917",
            "grand_total": "\u0915\u0941\u0932 \u092f\u094b\u0917",
        },
        "costs": {
            "title": "\u0926\u0930 \u0921\u0947\u091f\u093e\u092c\u0947\u0938",
            "rate": "\u0926\u0930",
            "material": "\u0938\u093e\u092e\u0917\u094d\u0930\u0940",
            "labor": "\u0936\u094d\u0930\u092e",
            "equipment": "\u0909\u092a\u0915\u0930\u0923",
            "search_costs": "\u0926\u0930\u0947\u0902 \u0916\u094b\u091c\u0947\u0902...",
        },
        "validation": {
            "title": "\u0938\u0924\u094d\u092f\u093e\u092a\u0928",
            "passed": "\u0909\u0924\u094d\u0924\u0940\u0930\u094d\u0923",
            "warnings": "\u091a\u0947\u0924\u093e\u0935\u0928\u0940",
            "errors": "\u0924\u094d\u0930\u0941\u091f\u093f\u092f\u093e\u0902",
            "score": "\u0917\u0941\u0923\u0935\u0924\u094d\u0924\u093e \u0905\u0902\u0915",
            "run_validation": "\u0938\u0924\u094d\u092f\u093e\u092a\u0928 \u091a\u0932\u093e\u090f\u0902",
            "missing_quantity": "\u092e\u0926 {position} \u092e\u0947\u0902 \u092e\u093e\u0924\u094d\u0930\u093e \u0928\u0939\u0940\u0902 \u0939\u0948",
            "missing_rate": "\u092e\u0926 {position} \u092e\u0947\u0902 \u0926\u0930 \u0928\u0939\u0940\u0902 \u0939\u0948",
            "missing_description": "\u092e\u0926 {position} \u092e\u0947\u0902 \u0935\u093f\u0935\u0930\u0923 \u0928\u0939\u0940\u0902 \u0939\u0948",
            "missing_classification": "\u092e\u0926 {position} \u0915\u094b \u0935\u0930\u094d\u0917\u0940\u0915\u0930\u0923 \u0915\u094b\u0921 \u091a\u093e\u0939\u093f\u090f",
            "duplicate_ordinal": "\u0926\u094b\u0939\u0930\u093e\u092f\u093e \u0915\u094d\u0930\u092e \u0938\u0902\u0916\u094d\u092f\u093e: {ordinal}",
            "rate_anomaly": "\u0926\u0930 {rate} \u0938\u0940\u092e\u093e \u0938\u0947 \u0905\u0927\u093f\u0915 \u0939\u0948 ({threshold})",
        },
        "cad": {
            "title": "CAD \u0906\u092f\u093e\u0924",
            "upload": "CAD \u092b\u093c\u093e\u0907\u0932 \u0905\u092a\u0932\u094b\u0921 \u0915\u0930\u0947\u0902",
            "supported_formats": "\u0938\u092e\u0930\u094d\u0925\u093f\u0924: DWG, DGN, RVT, IFC, PDF",
            "converting": "\u0930\u0942\u092a\u093e\u0902\u0924\u0930\u093f\u0924 \u0939\u094b \u0930\u0939\u093e \u0939\u0948...",
            "elements_found": "{count} \u0924\u0924\u094d\u0935 \u092e\u093f\u0932\u0947",
        },
        "takeoff": {
            "title": "\u092e\u093e\u0924\u094d\u0930\u093e \u0928\u093f\u0915\u093e\u0932\u0928\u093e",
            "auto_detect": "\u0938\u094d\u0935\u0924\u0903 \u092a\u0939\u091a\u093e\u0928",
            "manual_measure": "\u092e\u0948\u0928\u094d\u092f\u0941\u0905\u0932 \u092e\u093e\u092a\u0928",
            "confidence": "\u0935\u093f\u0936\u094d\u0935\u0938\u0928\u0940\u092f\u0924\u093e",
        },
        "tendering": {
            "title": "\u0928\u093f\u0935\u093f\u0926\u093e",
            "create_tender": "\u0928\u093f\u0935\u093f\u0926\u093e \u092c\u0928\u093e\u090f\u0902",
            "bid": "\u092c\u094b\u0932\u0940",
            "award": "\u0906\u0935\u0902\u091f\u0928",
        },
        "modules": {
            "title": "\u092e\u0949\u0921\u094d\u092f\u0942\u0932",
            "installed": "\u0938\u094d\u0925\u093e\u092a\u093f\u0924",
            "available": "\u0909\u092a\u0932\u092c\u094d\u0927",
            "install": "\u0938\u094d\u0925\u093e\u092a\u093f\u0924 \u0915\u0930\u0947\u0902",
            "uninstall": "\u0905\u0928\u0938\u094d\u0925\u093e\u092a\u093f\u0924 \u0915\u0930\u0947\u0902",
            "update": "\u0905\u092a\u0921\u0947\u091f \u0915\u0930\u0947\u0902",
        },
        "units": {
            "m": "\u092e\u0940",
            "m2": "\u092e\u0940\u00b2",
            "m3": "\u092e\u0940\u00b3",
            "kg": "\u0915\u093f\u0917\u094d\u0930\u093e",
            "t": "\u091f\u0928",
            "pcs": "\u0928\u0917",
            "lsum": "\u0928\u093f\u0936\u094d\u091a\u093f\u0924 \u0930\u093e\u0936\u093f",
            "h": "\u0918\u0902\u091f\u093e",
            "set": "\u0938\u0947\u091f",
        },
    }

    # -----------------------------------------------------------------
    # Write all 20 locale files
    # -----------------------------------------------------------------
    all_locales: dict[str, dict[str, dict[str, str]]] = {
        "en": en,
        "de": de,
        "ru": ru,
        "fr": fr,
        "es": es,
        "pt": pt,
        "it": it,
        "nl": nl,
        "pl": pl,
        "cs": cs,
        "tr": tr,
        "sv": sv,
        "no": no,
        "da": da,
        "fi": fi,
        "ar": ar,
        "zh": zh,
        "ja": ja,
        "ko": ko,
        "hi": hi,
    }

    for locale_code, data in all_locales.items():
        path = locales_dir / f"{locale_code}.json"
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
