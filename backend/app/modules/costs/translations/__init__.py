"""CWICR cost-database German→localized vocabulary translation.

The CWICR parquet files carry several columns whose values are frozen-German
across every regional database (BG_SOFIA, RO_BUCHAREST, SV_STOCKHOLM, ...).
That happens because the source data was originally German and the upstream
CWICR pipeline localizes only the descriptive long-text columns
(``rate_original_name``, ``subsection_name``, ``unit``), leaving the short
fixed-vocabulary tokens (row_type, classification.category, variant_stats
unit/group, German unit abbreviations) as-is.

This module ships a lookup table per supported locale that maps the known
German tokens to their localized equivalents. The lookup is applied at
response time in :mod:`app.modules.costs.router` so the on-disk CostItem
rows are not mutated — keeping the existing CWICR loader (v2.6.23) and the
SQLite cache untouched.

Design notes
------------
* **Per-locale JSON** at ``translations/<locale>.json``. Adding a language
  is one new JSON file; missing translations fall back to the German
  source value (so a half-translated catalogue is never blank, only
  partially localised).
* **Identity map** for ``de.json`` — guarantees the lookup always
  resolves, simplifies tests, and lets a German user see the canonical
  source even when the loader auto-translates (they explicitly want
  German).
* **Compound values are split** on the canonical CWICR separators
  (``", "`` for unit lists, ``", "`` + ``"="`` for ``key=value`` group
  lists). Each token is translated independently, so a never-before-seen
  token doesn't poison its neighbours.
* **No external dependencies** — pure Python + json. Translations are
  cached after first load (LRU-style dict).

Public API
----------
* :func:`load_translations` — read a locale's JSON dict (cached).
* :func:`translate_token` — translate a single short token, falls back
  to the input on miss.
* :func:`translate_unit_list` — handles compound CWICR unit strings like
  ``"100 Stück, kg, t, St"``.
* :func:`translate_group_list` — handles compound CWICR group strings like
  ``"m²=Geonetze und Geogitter, Stück=Geotextilien"``.
* :func:`localize_cost_row` — convenience wrapper that augments a single
  CostItem-shaped dict with ``*_localized`` mirror fields.
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger(__name__)

# Canonical separator the CWICR pipeline uses for compound values.
# Both the unit list and the group list join on `, ` (with a space).
_SEP = ", "
_GROUP_KV_SEP = "="

# Locales for which we ship a JSON file.  Order is documentation only —
# the actual list is derived from the directory contents at load time.
SUPPORTED_LOCALES = (
    "de",
    "en",
    "ro",
    "bg",
    "sv",
    "it",
    "nl",
    "pl",
    "cs",
    "hr",
    "tr",
    "id",
    "ja",
    "ko",
    "th",
    "vi",
)

_LOCALES_DIR = Path(__file__).parent


@lru_cache(maxsize=32)
def load_translations(locale: str) -> dict[str, str]:
    """Load and cache the translation dictionary for a single locale.

    Args:
        locale: Two-letter ISO 639-1 code (lowercased).

    Returns:
        ``{de_token: localized_token}`` dict, or an empty dict when the
        locale has no JSON file. Empty-dict means "fall back to German
        source value for every key" — never raises.
    """
    loc = (locale or "").strip().lower()
    if not loc:
        return {}

    path = _LOCALES_DIR / f"{loc}.json"
    if not path.is_file():
        return {}

    try:
        with path.open("r", encoding="utf-8") as fh:
            raw = json.load(fh)
        if not isinstance(raw, dict):
            logger.warning("Translation file %s is not a JSON object — ignoring", path)
            return {}
        # Coerce values to str so a typo `42` int doesn't crash str.format.
        return {str(k): str(v) for k, v in raw.items()}
    except (OSError, json.JSONDecodeError):
        logger.exception("Failed to load translation file: %s", path)
        return {}


def translate_token(token: str, locale: str) -> str:
    """Translate a single fixed-vocabulary token, falling back to the input.

    The lookup is exact (case-sensitive) — CWICR tokens are stable
    so a fuzzy match is unnecessary and would introduce false positives
    for free-form variant labels that happen to start the same way.

    Args:
        token: German source value, e.g. ``"Stück"`` or ``"Geotextilien"``.
        locale: Target locale, e.g. ``"ro"``.

    Returns:
        Localized token if known, otherwise the input unchanged so the UI
        still shows *something* readable. The fallback is intentional —
        the user spec says "better wrong than misleading", which here
        means: leave a German term untranslated rather than guessing.
    """
    if not token:
        return token
    table = load_translations(locale)
    if not table:
        return token
    return table.get(token, token)


def translate_unit_list(value: str, locale: str) -> str:
    """Translate a compound CWICR unit list ``"100 Stück, kg, t, St"``.

    Each comma-separated token is translated independently; unknown
    tokens stay German.  Returns the joined localized string.
    """
    if not value:
        return value
    parts = [p.strip() for p in value.split(_SEP)]
    return _SEP.join(translate_token(p, locale) for p in parts if p)


def translate_group_list(value: str, locale: str) -> str:
    """Translate a CWICR group string of the form ``"key=val, key=val"``.

    Both sides of the ``=`` are translated.  The key tends to be a unit
    (``m²``, ``Stück``) and the value a German material category
    (``Geotextilien``, ``Stahlseile``).  Unknown tokens fall back to
    the German source.  Returns the joined localized string.
    """
    if not value:
        return value
    parts = [p.strip() for p in value.split(_SEP)]
    out: list[str] = []
    for part in parts:
        if not part:
            continue
        if _GROUP_KV_SEP in part:
            key, _, val = part.partition(_GROUP_KV_SEP)
            out.append(
                f"{translate_token(key.strip(), locale)}"
                f"{_GROUP_KV_SEP}"
                f"{translate_token(val.strip(), locale)}"
            )
        else:
            out.append(translate_token(part, locale))
    return _SEP.join(out)


def localize_cost_row(
    *,
    classification: dict[str, str] | None,
    metadata: dict | None,
    components: list[dict] | None,
    locale: str,
) -> tuple[dict[str, str], dict, list[dict]]:
    """Augment a CostItem row with ``*_localized`` mirror fields.

    The original German values stay where they are — UIs that haven't
    migrated to read the ``_localized`` mirror keep working.  The mirror
    fields appear next to the source so the frontend can do a simple
    ``localized || source`` fallback without a second API call.

    Touched fields:
        * ``classification.category_localized`` — fixes ``"BAUARBEITEN"``.
        * ``metadata.variant_stats.unit_localized`` — fixes ``"100 Stück"``.
        * ``metadata.variant_stats.group_localized`` — fixes
          ``"m²=Geonetze und Geogitter"``.
        * Per-component ``components[i].unit_localized`` — fixes
          ``"Std."`` / ``"Masch.-Std."`` (German hour abbreviations
          that leak through from the resource sheet).

    Returns:
        ``(classification, metadata, components)`` — same objects, mutated
        in place and also returned for ergonomic chaining.
    """
    cls = classification or {}
    meta = metadata or {}
    comps = components or []

    # --- classification.category ---------------------------------------
    cat = cls.get("category")
    if isinstance(cat, str) and cat:
        cls["category_localized"] = translate_token(cat, locale)

    # --- metadata.variant_stats.unit / group ---------------------------
    stats = meta.get("variant_stats")
    if isinstance(stats, dict):
        unit_val = stats.get("unit")
        if isinstance(unit_val, str) and unit_val:
            stats["unit_localized"] = translate_unit_list(unit_val, locale)
        group_val = stats.get("group")
        if isinstance(group_val, str) and group_val:
            stats["group_localized"] = translate_group_list(group_val, locale)

    # --- components[].unit ---------------------------------------------
    for cm in comps:
        if not isinstance(cm, dict):
            continue
        u = cm.get("unit")
        if isinstance(u, str) and u:
            cm["unit_localized"] = translate_token(u, locale)

    return cls, meta, comps


__all__ = [
    "SUPPORTED_LOCALES",
    "load_translations",
    "translate_token",
    "translate_unit_list",
    "translate_group_list",
    "localize_cost_row",
]
