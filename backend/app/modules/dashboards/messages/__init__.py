"""Locale-scoped message bundle for the dashboards module.

Mirrors :mod:`app.core.validation.messages` and delegates to the same
:class:`~app.core.validation.messages.MessageBundle` implementation —
the class is generic, only its path is module-specific.

Usage:
    from app.modules.dashboards.messages import translate
    translate("snapshot.label.duplicate", locale="de")
"""

from __future__ import annotations

from pathlib import Path

from app.core.validation.messages import MessageBundle

DEFAULT_LOCALE = "en"
_MESSAGES_DIR = Path(__file__).parent
_bundle = MessageBundle(messages_dir=_MESSAGES_DIR)


def translate(key: str, locale: str = DEFAULT_LOCALE, **params: object) -> str:
    """Return the translated message for ``key`` in ``locale``.

    Follows the standard fallback chain: requested locale → ``en`` →
    raw key (with a deduped WARNING log). See
    :func:`app.core.validation.messages.translate` for the semantics —
    this is a thin wrapper that binds the dashboards bundle.
    """
    return _bundle.translate(key, locale=locale, **params)


def is_key_present(key: str, locale: str = DEFAULT_LOCALE) -> bool:
    """Diagnostic — used by tests to assert locale-coverage parity."""
    return _bundle.is_key_present(key, locale=locale)


def available_locales() -> list[str]:
    return _bundle.available_locales()


def reload_bundle() -> None:
    """Force the bundle to re-read its JSON files. Test-only."""
    _bundle.reload()
