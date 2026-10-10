# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Locale-scoped message bundle for the submittal register rules.

The seven submission-gate findings live in the shared validation bundle. The
register findings (stamp against status, resubmission link, lead time,
approval needed-by) live here, the way the contracts module keeps its payment
application findings, because a module bundle can grow one language at a time
while the shared bundle requires every locale it carries to answer every key.

It constructs the shared :class:`~app.core.validation.messages.MessageBundle`,
so a regional code such as ``tr-TR`` resolves through its base language and a
key missing from a locale falls back to English rather than to the raw key.

Public API
    * :func:`translate(key, locale="en", **params) -> str`
    * :func:`is_key_present(key, locale)` - diagnostic used by tests.
    * :func:`available_locales() -> list[str]`
"""

from __future__ import annotations

from pathlib import Path

from app.core.validation.messages import MessageBundle

DEFAULT_LOCALE = "en"
_MESSAGES_DIR = Path(__file__).parent
_bundle = MessageBundle(messages_dir=_MESSAGES_DIR)


def translate(key: str, locale: str = DEFAULT_LOCALE, **params: object) -> str:
    """Resolve a submittal message key for ``locale`` with ``str.format`` params."""
    return _bundle.translate(key, locale=locale, **params)


def is_key_present(key: str, locale: str = DEFAULT_LOCALE) -> bool:
    """Return ``True`` if ``key`` exists in ``locale`` without any fallback."""
    return _bundle.is_key_present(key, locale=locale)


def available_locales() -> list[str]:
    """List locales currently loaded into the submittals bundle."""
    return _bundle.available_locales()


__all__ = ["available_locales", "is_key_present", "translate"]
