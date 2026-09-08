# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Internationalization system.

37 languages built into core. Zero hardcoded strings.
New language = add a JSON file to locales/ AND an entry in both lists below.
A file without a list entry is unreachable, because every caller that picks a
locale (the Accept-Language middleware, the /i18n routes) gates on
SUPPORTED_LOCALES; a list entry without a file is a language offered by
get_available_locales() that silently serves English. tests/unit/
test_backend_locale_catalogue.py holds the two sides equal.

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
    "bg",  # Bulgarian (Български)
    "hr",  # Croatian (Hrvatski)
    "id",  # Indonesian (Bahasa Indonesia)
    "ro",  # Romanian (Română)
    "th",  # Thai (ไทย)
    "vi",  # Vietnamese (Tiếng Việt)
    "uk",  # Ukrainian (Українська)
    "uz",  # Uzbek (Oʻzbekcha), Latin script since 1993
    "et",  # Estonian (Eesti)
    "ky",  # Kyrgyz (Кыргызча)
    "bn",  # Bengali (বাংলা)
    "kk",  # Kazakh (Қазақша)
    "fil",  # Filipino
    "ur",  # Urdu (اردو), right-to-left
    "fa",  # Persian (فارسی), right-to-left
    "he",  # Hebrew (עברית), right-to-left
    "el",  # Greek (Ελληνικά)
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
    "bg": "Български",
    "hr": "Hrvatski",
    "id": "Bahasa Indonesia",
    "ro": "Română",
    "th": "ไทย",
    "vi": "Tiếng Việt",
    "uk": "Українська",
    # U+02BB MODIFIER LETTER TURNED COMMA, not an ASCII apostrophe: in Uzbek
    # the mark is a letter, and O' spells a different sound from Oʻ.
    "uz": "Oʻzbekcha",
    "et": "Eesti",
    "ky": "Кыргызча",
    "bn": "বাংলা",
    "kk": "Қазақша",
    "fil": "Filipino",
    "ur": "اردو",
    "fa": "فارسی",
    "he": "עברית",
    "el": "Ελληνικά",
}

LOCALES_DIR = Path(__file__).parent.parent.parent / "locales"


def load_translations(locales_dir: Path | None = None) -> None:
    """Load all locale JSON files into memory."""
    global _translations
    scan_dir = locales_dir or LOCALES_DIR

    if not scan_dir.exists():
        # This used to create the directory and refill it from an embedded copy
        # of the catalogue. The copy knew 20 of the 28 languages and a far
        # smaller key set, so the recovery reported success and left the
        # platform serving a catalogue missing most of its strings, with every
        # file present, parsing and internally consistent - a state no guard we
        # have can see, because the files agree with each other. Recovering the
        # wrong data is worse than not recovering, so it says so instead.
        raise FileNotFoundError(
            f"Locales directory not found: {scan_dir}. Every way of shipping the platform carries it, "
            f"so an absence here is a defect in the build that produced this install rather than "
            f"anything wrong with the machine running it. In a source tree restore it with "
            f"'git checkout -- backend/locales'; in an installed copy reinstall the package. If this "
            f"path is inside a temporary directory the process unpacked itself into, it is a desktop "
            f"build that was assembled without the catalogue, no local step can put it back, and the "
            f"only fix is a corrected build."
        )

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


def locale_candidates(locale: str) -> tuple[str, ...]:
    """``locale`` and, for a regional code, its base language, in that order.

    One definition, because the tree already held several and they did not
    agree. The Accept-Language middleware strips the region before it reaches
    this module, the document locale resolver strips it too, and the /i18n
    routes and ``t()`` did not strip it at all. A reader whose browser says
    pt-BR therefore got Portuguese out of anything the middleware touched and
    English, or a 404, out of everything addressed by code.

    Case is folded here rather than at each call site: locale files are named
    in lower case and every list in this module is written in lower case, so a
    code that arrives capitalised is the same request, not a different one.
    """
    lowered = locale.strip().lower()
    if "-" in lowered:
        return (lowered, lowered.split("-", 1)[0])
    return (lowered,)


def resolve_locale(locale: str) -> str | None:
    """The catalogue that actually answers for ``locale``, or None.

    None means nothing but English is available, which is a different
    statement from ``is_locale_loaded`` returning False: pt-BR has no
    catalogue of its own and still resolves, through pt.
    """
    for candidate in locale_candidates(locale):
        if candidate in _translations:
            return candidate
    return None


def set_locale(locale: str) -> None:
    """Set current locale for this context (request).

    Stores the code that will really be rendered, so ``get_locale`` reports
    what a reader is about to see. A regional code lands on its base language
    rather than on English.
    """
    _current_locale.set(resolve_locale(locale) or "en")


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

    # Requested locale, then its base language, then English, then the raw key,
    # and the walk is per key rather than per catalogue: a language whose file
    # is missing a string should give up that one string to English, not the
    # whole page.
    #
    # The base-language step is not decoration. The UI offers five regional
    # codes, en-US, es-CL, es-CO, es-MX and pt-BR, and resolves each of them
    # through its base so a Brazilian reader gets the Portuguese string. The
    # backend catalogue has a file for none of the five, and without this step
    # it went straight past a translated pt to English: the same person read
    # Portuguese on screen and English in everything the server writes, with
    # the string sitting right there.
    template: str | None = None
    for candidate in locale_candidates(loc):
        template = _translations.get(candidate, {}).get(key)
        if template is not None:
            break
    template = template or _translations.get("en", {}).get(key) or key

    if kwargs:
        try:
            return template.format(**kwargs)
        except (KeyError, ValueError, IndexError) as exc:
            # The braces in a locale value are code, and a translation pass is
            # where they get eaten. A renamed field raises KeyError and an
            # unbalanced brace ValueError, both of which fell back here, but a
            # positional {0} or a bare {} raises IndexError, which did not:
            # rendering any route that reached such a value returned a 500.
            # None of the three is worth failing a request over, and none of
            # them should be silent either, or a locale can serve half-rendered
            # text for as long as nobody reads that screen closely.
            logger.warning("Interpolation failed for %r in locale %r: %s", key, loc, exc)
            return template

    return template


def get_all_translations(locale: str) -> dict[str, str]:
    """Get all translations for a locale (for frontend bundle).

    Resolves a regional code through its base language for the same reason
    ``t`` does: pt-BR has no catalogue of its own and pt does, and handing back
    English for it would contradict what the same request gets key by key.
    """
    resolved = resolve_locale(locale)
    if resolved is not None:
        return _translations[resolved]
    return _translations.get("en", {})


def is_locale_loaded(locale: str) -> bool:
    """Return True if a translation bundle for ``locale`` itself is in memory.

    Exact membership, deliberately. ``resolve_locale`` is the function that
    answers the question a reader cares about, which is whether anything but
    English is going to come back, and pt-BR answers False here and pt there.
    """
    return locale in _translations


def get_available_locales() -> list[dict[str, object]]:
    """List available locales with their display names."""
    return [
        {"code": code, "name": LOCALE_NAMES.get(code, code), "loaded": code in _translations}
        for code in SUPPORTED_LOCALES
    ]
