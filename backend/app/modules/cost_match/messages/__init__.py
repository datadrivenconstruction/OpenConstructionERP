"""Locale-scoped message bundle for the cost_match module.

Populated as T12 lands. Shares the
:class:`~app.core.validation.messages.MessageBundle` implementation —
see :mod:`app.modules.dashboards.messages` for the pattern.
"""

from __future__ import annotations

from pathlib import Path

from app.core.validation.messages import MessageBundle

DEFAULT_LOCALE = "en"
_MESSAGES_DIR = Path(__file__).parent
_bundle = MessageBundle(messages_dir=_MESSAGES_DIR)


def translate(key: str, locale: str = DEFAULT_LOCALE, **params: object) -> str:
    return _bundle.translate(key, locale=locale, **params)


def is_key_present(key: str, locale: str = DEFAULT_LOCALE) -> bool:
    return _bundle.is_key_present(key, locale=locale)


def available_locales() -> list[str]:
    return _bundle.available_locales()
