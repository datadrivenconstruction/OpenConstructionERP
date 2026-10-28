# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Document and email text for the languages a module does not carry in its own file.

A module that writes text for people outside the platform (an invitation, a
workbook header, a notification) keeps its first languages in a table next to
its code. The rest of :data:`app.core.i18n.SUPPORTED_LOCALES` lives in the
platform's locale files, ``backend/locales/<code>.json``, under one group with
a named section per module, the same files and the same translation workflow as
every other backend string::

    locales/ja.json  ->  {"document_catalogue": {"portal_login": {...}, "tender_xlsx": {...}, ...}, ...}

A module asks for its section with :func:`section` and adds the languages its
own table lacks with :func:`merge_missing`. The module's table always wins, so
a language translated in code is never overridden by a file.

Every language carries every section, English included. The English entry is a
copy of the module's own table (a test holds the two equal), which gives the
locale files one key set to be measured against. :func:`section` leaves English
out for that reason: it is the module's own and is never read from here.

Every value is plain text with the same ``{placeholders}`` as English. The files
are read once, on first use.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

from app.core.i18n import LOCALES_DIR

logger = logging.getLogger(__name__)

#: The group of every locale file that holds these sections.
GROUP = "document_catalogue"

#: Languages written right to left. Documents set the reading direction for these.
RTL_LOCALES: frozenset[str] = frozenset({"ar", "fa", "he", "ur"})

__all__ = ["GROUP", "RTL_LOCALES", "english_section", "is_rtl", "merge_missing", "section"]


def is_rtl(locale: str | None) -> bool:
    """Whether ``locale`` (``ar``, ``fa-IR``, ...) is written right to left."""
    return bool(locale) and str(locale).strip().lower().replace("_", "-").split("-")[0] in RTL_LOCALES


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, Any]]:
    """Every locale file's catalogue group: ``{locale: {section: payload}}``."""
    loaded: dict[str, dict[str, Any]] = {}
    if not LOCALES_DIR.is_dir():
        return loaded
    for path in sorted(LOCALES_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("locale file %s is unreadable; its document catalogue was skipped", path.name, exc_info=True)
            continue
        block = data.get(GROUP) if isinstance(data, dict) else None
        if isinstance(block, dict):
            loaded[path.stem] = block
    return loaded


def section(name: str) -> dict[str, Any]:
    """The payload of section ``name`` for every language but English, by language code."""
    return {locale: sections[name] for locale, sections in _load().items() if name in sections and locale != "en"}


def english_section(name: str) -> Any:
    """The English copy of section ``name`` held in ``locales/en.json``, or ``None``."""
    return _load().get("en", {}).get(name)


def merge_missing(table: dict[str, Any], name: str) -> None:
    """Add the languages ``table`` lacks from section ``name``; existing languages are left alone."""
    for locale, payload in section(name).items():
        table.setdefault(locale, payload)
