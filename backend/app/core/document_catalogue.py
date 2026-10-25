# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Document and email text for the languages a module does not carry in its own file.

A module that writes text for people outside the platform (an invitation, a
workbook header, a notification) keeps its first languages in a table next to
its code. The rest of :data:`app.core.i18n.SUPPORTED_LOCALES` lives here, one
JSON file per language in ``document_catalogues/``, each holding named
sections::

    document_catalogues/ja.json  ->  {"portal_login": {...}, "tender_xlsx": {...}, ...}

A module asks for its section with :func:`section` and adds the languages its
own table lacks with :func:`merge_missing`. The module's table always wins, so
a language translated in code is never overridden by a file.

Every value is plain text with the same ``{placeholders}`` as English. The files
are read once, on first use.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

CATALOGUE_DIR = Path(__file__).parent / "document_catalogues"

#: Languages written right to left. Documents set the reading direction for these.
RTL_LOCALES: frozenset[str] = frozenset({"ar", "fa", "he", "ur"})

__all__ = ["CATALOGUE_DIR", "RTL_LOCALES", "is_rtl", "merge_missing", "section"]


def is_rtl(locale: str | None) -> bool:
    """Whether ``locale`` (``ar``, ``fa-IR``, ...) is written right to left."""
    return bool(locale) and str(locale).strip().lower().replace("_", "-").split("-")[0] in RTL_LOCALES


@lru_cache(maxsize=1)
def _load() -> dict[str, dict[str, Any]]:
    """Every catalogue file: ``{locale: {section: payload}}``."""
    loaded: dict[str, dict[str, Any]] = {}
    if not CATALOGUE_DIR.is_dir():
        return loaded
    for path in sorted(CATALOGUE_DIR.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("document catalogue %s is unreadable and was skipped", path.name, exc_info=True)
            continue
        if isinstance(data, dict):
            loaded[path.stem] = data
    return loaded


def section(name: str) -> dict[str, Any]:
    """The payload of section ``name`` for every language that has one, by language code."""
    return {locale: sections[name] for locale, sections in _load().items() if name in sections}


def merge_missing(table: dict[str, Any], name: str) -> None:
    """Add the languages ``table`` lacks from section ``name``; existing languages are left alone."""
    for locale, payload in section(name).items():
        table.setdefault(locale, payload)
