"""‌⁠‍LocalizedStr utility for multi-language JSONB string storage and resolution.

Provides a Pydantic v2 model for storing translations as ``{"en": "...", "de": "..."}``
and resolving them against the current request locale (via ``get_locale``).

Usage::

    from app.core.localized_string import LocalizedStr, resolve_localized

    name = LocalizedStr(translations={"en": "Germany", "de": "Deutschland", "ru": "Германия"})
    print(name.resolve("de"))       # "Deutschland"
    print(name.resolve("ja"))       # falls back to "en" → "Germany"
    print(resolve_localized(None))  # ""
"""

from __future__ import annotations

from pydantic import BaseModel

__all__ = [
    "LocalizedStr",
    "resolve_localized",
]


class LocalizedStr(BaseModel):
    """‌⁠‍A multi-language string stored as a dict of locale → text.

    Attributes:
        translations: Mapping of ISO 639-1 locale codes to translated text.
    """

    translations: dict[str, str]

    # ------------------------------------------------------------------
    # Instance methods
    # ------------------------------------------------------------------

    def resolve(self, locale: str = "en", fallback: str = "en") -> str:
        """‌⁠‍Get translation for *locale*, falling back gracefully.

        Resolution order:
        1. Exact *locale* match.
        2. *fallback* locale (default ``"en"``).
        3. First available translation (alphabetical by locale).
        4. Empty string ``""``.

        Args:
            locale: Desired locale code (e.g. ``"de"``).
            fallback: Fallback locale code when *locale* is missing.

        Returns:
            The resolved translation string, or ``""`` if none available.
        """
        if locale in self.translations:
            return self.translations[locale]
        if fallback in self.translations:
            return self.translations[fallback]
        if self.translations:
            return self.translations[sorted(self.translations)[0]]
        return ""

    def get(self, locale: str) -> str | None:
        """Get translation for an exact locale, or ``None`` if missing.

        Args:
            locale: Locale code to look up.

        Returns:
            The translation string, or ``None``.
        """
        return self.translations.get(locale)

    def set(self, locale: str, value: str) -> LocalizedStr:
        """Return a new instance with the given locale set or updated.

        The original instance is **not** mutated.

        Args:
            locale: Locale code to set.
            value: Translation text.

        Returns:
            A new ``LocalizedStr`` with the updated translations.
        """
        updated = {**self.translations, locale: value}
        return LocalizedStr(translations=updated)

    def locales(self) -> list[str]:
        """Return sorted list of locales that have translations.

        Returns:
            Sorted list of locale code strings.
        """
        return sorted(self.translations)

    def is_complete(self, required_locales: list[str] | None = None) -> bool:
        """Check whether all required locales have non-empty values.

        When *required_locales* is ``None``, checks that **every** existing
        translation is non-empty (i.e. there are no blank entries).

        Args:
            required_locales: Optional list of locale codes that must be present
                and non-empty.

        Returns:
            ``True`` if completeness check passes.
        """
        if required_locales is not None:
            return all(bool(self.translations.get(loc)) for loc in required_locales)
        # No required list → every existing value must be non-empty.
        return bool(self.translations) and all(bool(v) for v in self.translations.values())

    # ------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------

    def __str__(self) -> str:
        """Resolve using the current i18n context locale.

        Imports ``get_locale`` lazily to avoid circular imports at module
        load time.
        """
        from app.core.i18n import get_locale  # lazy import

        return self.resolve(locale=get_locale())

    def __len__(self) -> int:
        """Return number of translations."""
        return len(self.translations)

    # ------------------------------------------------------------------
    # Class methods / constructors
    # ------------------------------------------------------------------

    @classmethod
    def from_single(cls, value: str, locale: str = "en") -> LocalizedStr:
        """Create a ``LocalizedStr`` from a single translation.

        Args:
            value: The translation text.
            locale: The locale code (default ``"en"``).

        Returns:
            A new ``LocalizedStr`` with one entry.
        """
        return cls(translations={locale: value})

    @classmethod
    def empty(cls) -> LocalizedStr:
        """Create an empty ``LocalizedStr`` with no translations.

        Returns:
            A new ``LocalizedStr`` with an empty translations dict.
        """
        return cls(translations={})


# ----------------------------------------------------------------------
# Standalone helper
# ----------------------------------------------------------------------


def resolve_localized(
    data: dict[str, str] | str | None,
    locale: str = "en",
    fallback: str = "en",
) -> str:
    """Resolve a localized value from raw data without constructing ``LocalizedStr``.

    Handy for resolving JSONB column values directly.

    Args:
        data: One of:
            - ``dict`` mapping locale codes to strings.
            - ``str`` (plain, non-localized value — returned as-is).
            - ``None`` (returns ``""``).
        locale: Desired locale code.
        fallback: Fallback locale code.

    Returns:
        Resolved translation string, the plain string, or ``""``.
    """
    if data is None:
        return ""
    if isinstance(data, str):
        return data
    # dict path — same resolution logic as LocalizedStr.resolve
    if locale in data:
        return data[locale]
    if fallback in data:
        return data[fallback]
    if data:
        return data[sorted(data)[0]]
    return ""
