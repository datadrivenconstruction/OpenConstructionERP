"""Filesystem layout for downloaded dictionaries and translation cache.

All translation-related state lives under ``~/.openestimate/translations/``
unless overridden:

    translations/
    ├── cache.db                # SQLite cache of past translations
    ├── muse/                   # MUSE bilingual dictionaries
    │   ├── en-bg.tsv
    │   ├── en-de.tsv
    │   └── ...
    └── iate/                   # IATE EU termbase pairs (extracted)
        ├── en-bg.tsv
        └── ...

Splitting this into its own tiny module avoids import-time circles between
``cache``, ``lookup``, and ``downloader``.
"""

from __future__ import annotations

from pathlib import Path


def translations_root(root: str | None = None) -> Path:
    """Return the root directory for translation state, creating if needed."""
    if root:
        path = Path(root).expanduser()
    else:
        path = Path.home() / ".openestimate" / "translations"
    path.mkdir(parents=True, exist_ok=True)
    return path


def dictionary_dir(root: str | None = None) -> Path:
    """Root for ``{muse,iate}/`` subdirectories."""
    return translations_root(root)


def cache_db_path(override: str | None = None) -> Path:
    """Return the path to the SQLite cache file."""
    if override:
        return Path(override).expanduser()
    return translations_root() / "cache.db"
