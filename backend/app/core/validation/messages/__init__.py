# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Locale-scoped message bundle for validation rules.

OpenEstimate principle #2: i18n EVERYWHERE - zero hardcoded strings.

This package ships a self-contained translation bundle for the 42+ built-in
validation rules. Each rule's user-facing ``message`` and ``suggestion`` text
is stored in per-locale JSON files (``en.json``, ``de.json``, ``ru.json``,
…) and resolved at runtime via :func:`translate`.

Design notes
------------
* **Self-contained.** The bundle lives alongside the rules it translates.
  This keeps the module "plugin-like" - a third-party rules package can
  carry its own ``messages/`` directory and register itself without
  touching the global :mod:`app.core.i18n` locales.
* **Same resolution semantics as ``app.core.i18n.t()``**, and now actually
  implemented that way rather than merely documented that way: this used to
  claim lockstep with ``t()`` while doing a bare exact-locale match with no
  base-language step, so ``translate(key, locale="es-MX")`` returned English
  even on a key ``es.json`` answers in full. Fallback chain: requested locale
  → its base language for a regional code, via :func:`app.core.i18n.locale_candidates`
  (the same helper ``t()`` uses - one resolution rule, not two that could
  disagree) → ``en`` → raw key (logged as WARNING). A successful base-language
  resolution is not itself a fallback and logs nothing; only bottoming out at
  ``en`` does.
* **In-memory cache.** JSON is loaded once on first access and flattened
  into a dot-notation lookup table. Explicit reload is possible via
  :func:`reload_bundle` (used by tests).
* **Python ``str.format`` placeholders.** Matches the existing i18n
  convention so patterns like ``{ordinal}`` work unchanged.

Public API
----------
* :func:`translate(key, locale="en", **params) -> str`
* :func:`is_key_present(key, locale)` - diagnostic used by tests to assert
  locale coverage.
* :func:`available_locales() -> list[str]`
* :func:`reload_bundle()` - force re-read from disk (test helper).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from threading import Lock
from typing import Any

from app.core.i18n import locale_candidates

logger = logging.getLogger(__name__)

DEFAULT_LOCALE = "en"
_MESSAGES_DIR = Path(__file__).parent
_LOAD_LOCK = Lock()


class MessageBundle:
    """In-memory bundle of flattened translation keys, keyed by locale.

    The bundle is lazily populated on first use. Subsequent calls hit an
    in-memory cache; there is no per-call disk I/O.

    Attributes:
        messages_dir: Directory containing ``<locale>.json`` files.
    """

    def __init__(self, messages_dir: Path | None = None) -> None:
        self.messages_dir = messages_dir or _MESSAGES_DIR
        self._loaded: dict[str, dict[str, str]] = {}
        self._loaded_from: Path | None = None
        # Track which (locale, key) fallbacks have been logged so the
        # validator doesn't spam logs when the same key is missing on
        # every position in a BOQ.
        self._warned_fallbacks: set[tuple[str, str]] = set()
        self._warned_missing: set[str] = set()

    def load(self) -> None:
        """Eager-load all locale files from ``messages_dir``.

        Idempotent: subsequent calls short-circuit unless ``reload`` is
        requested explicitly via :meth:`reload`.
        """
        if self._loaded and self._loaded_from == self.messages_dir:
            return
        self._loaded.clear()
        self._warned_fallbacks.clear()
        self._warned_missing.clear()
        if not self.messages_dir.exists():
            logger.warning(
                "Validation messages directory missing: %s - all keys will fall back to raw key names",
                self.messages_dir,
            )
            self._loaded_from = self.messages_dir
            return
        for locale_file in sorted(self.messages_dir.glob("*.json")):
            locale = locale_file.stem
            try:
                with locale_file.open(encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError) as exc:
                logger.exception("Failed to load validation messages for '%s': %s", locale, exc)
                continue
            self._loaded[locale] = _flatten(data)
            logger.debug(
                "Loaded validation messages for '%s' (%d keys)",
                locale,
                len(self._loaded[locale]),
            )
        self._loaded_from = self.messages_dir
        logger.info(
            "Validation message bundle ready: locales=%s",
            sorted(self._loaded.keys()),
        )

    def reload(self) -> None:
        """Drop the cache and re-read every locale file from disk."""
        self._loaded.clear()
        self._loaded_from = None
        self._warned_fallbacks.clear()
        self._warned_missing.clear()
        self.load()

    def translate(
        self,
        key: str,
        locale: str = DEFAULT_LOCALE,
        **params: Any,
    ) -> str:
        """Resolve ``key`` to a localized string.

        Resolution order:
            1. ``locale`` bundle (exact match)
            2. ``locale``'s base language, for a regional code, via the same
               :func:`app.core.i18n.locale_candidates` chain the backend's
               own translator uses (``es-MX`` -> ``es``; a no-op for a
               base-only code, which every currently-reachable locale is)
            3. ``en`` bundle (the source of truth)
            4. raw ``key`` (logged as WARNING)

        A resolution that succeeds at step 2 is not a fallback and logs
        nothing - only bottoming out at ``en`` (step 3) does.

        Args:
            key: Dot-notation lookup key, e.g. ``"din276.cost_group_required.fail"``.
            locale: ISO 639-1 locale code, optionally with a region subtag
                (e.g. ``"es-MX"``). Unknown locales fall back to ``en``.
            **params: ``str.format``-style interpolation values.

        Returns:
            The resolved, formatted string - never ``None``.
        """
        with _LOAD_LOCK:
            self.load()

        en_bundle = self._loaded.get(DEFAULT_LOCALE, {})
        candidates = locale_candidates(locale)

        template: str | None = None
        for candidate in candidates:
            bundle = self._loaded.get(candidate)
            if bundle is None:
                continue
            template = bundle.get(key)
            if template is not None:
                break

        if template is None:
            template = en_bundle.get(key)
            if template is not None and locale != DEFAULT_LOCALE:
                warn_key = (locale, key)
                if warn_key not in self._warned_fallbacks:
                    self._warned_fallbacks.add(warn_key)
                    if any(candidate in self._loaded for candidate in candidates):
                        logger.warning(
                            "Validation message key '%s' missing for locale '%s' - falling back to '%s'",
                            key,
                            locale,
                            DEFAULT_LOCALE,
                        )
                    else:
                        # A module bundle ships the languages its authors wrote (en and de for most);
                        # English for the rest is the designed fallback, not a fault of a healthy install.
                        logger.info(
                            "Validation locale '%s' not loaded - falling back to '%s' for key '%s'",
                            locale,
                            DEFAULT_LOCALE,
                            key,
                        )
        if template is None:
            if key not in self._warned_missing:
                self._warned_missing.add(key)
                logger.warning(
                    "Validation message key '%s' not found in any locale "
                    "(requested '%s') - rendering humanised fallback",
                    key,
                    locale,
                )
            # Never leak the raw dotted key to an end user (NEW-I18N-001):
            # humanise the last path segment into a readable phrase. The
            # logged WARNING above still carries the exact key for devs.
            return _render_missing(key, params)

        if not params:
            return template
        try:
            return template.format(**params)
        except (KeyError, IndexError, ValueError) as exc:
            logger.warning(
                "Validation message template '%s' could not be formatted with params=%s: %s",
                key,
                sorted(params.keys()),
                exc,
            )
            return template

    def label_texts(
        self, key: str | None, labels: dict[str, str] | None, locale: str = DEFAULT_LOCALE
    ) -> dict[str, str] | None:
        """The ``text`` half of a ``{key, text}`` catalogue label, resolved for ``locale``.

        A tenant catalogue carries its own ``labels`` and they win. A shipped one carries only an
        i18n ``key``: when this bundle knows it, the text for the locale (English as the fallback)
        is returned, so the reader gets a name even when the screen's own locale file lacks the key.
        ``None`` when neither source names the item; the caller keeps the key.
        """
        if labels:
            return dict(labels)
        if not key or not self.is_key_present(key, DEFAULT_LOCALE):
            return None
        return {locale: self.translate(key, locale=locale)}

    def is_key_present(self, key: str, locale: str = DEFAULT_LOCALE) -> bool:
        """Return ``True`` if ``key`` exists in ``locale`` without any fallback."""
        with _LOAD_LOCK:
            self.load()
        return key in self._loaded.get(locale, {})

    def available_locales(self) -> list[str]:
        """Return a sorted list of locales currently loaded into the bundle."""
        with _LOAD_LOCK:
            self.load()
        return sorted(self._loaded.keys())

    def keys(self, locale: str = DEFAULT_LOCALE) -> set[str]:
        """Return all translation keys available for ``locale`` (for coverage tests)."""
        with _LOAD_LOCK:
            self.load()
        return set(self._loaded.get(locale, {}).keys())


def _flatten(data: dict[str, Any], prefix: str = "") -> dict[str, str]:
    """Flatten a nested dict into dot-notation keys.

    Mirrors the helper in :mod:`app.core.i18n` so both bundles use the
    same JSON authoring style.
    """
    flat: dict[str, str] = {}
    for raw_key, value in data.items():
        key = f"{prefix}.{raw_key}" if prefix else raw_key
        if isinstance(value, dict):
            flat.update(_flatten(value, key))
        else:
            flat[key] = str(value)
    return flat


def _humanise_key(key: str) -> str:
    """Turn a dotted lookup key into a readable phrase.

    ``"din276.cost_group_required.fail"`` → ``"Cost group required"``.
    The last path segment is the most specific label; ``fail`` / ``pass``
    / ``warn`` / ``info`` / ``error`` / ``message`` / ``suggestion`` are
    boilerplate result-state suffixes, so when the final segment is one of
    those we humanise the segment before it instead.
    """
    _STATE_SUFFIXES = {
        "fail",
        "pass",
        "warn",
        "warning",
        "info",
        "error",
        "ok",
        "message",
        "suggestion",
    }
    segments = [s for s in key.replace("/", ".").split(".") if s]
    if not segments:
        return "Validation issue"
    label = segments[-1]
    if label.lower() in _STATE_SUFFIXES and len(segments) >= 2:
        label = segments[-2]
    words = label.replace("_", " ").replace("-", " ").strip()
    if not words:
        return "Validation issue"
    return words[0].upper() + words[1:]


def _render_missing(key: str, params: dict[str, Any]) -> str:
    """Graceful missing-key fallback (NEW-I18N-001).

    Returns a human-readable phrase derived from the key's last meaningful
    path segment instead of the raw dotted key - an end user must never see
    ``"nonexistent.key.xyz"``. The exact key is still logged at WARNING for
    developers, and any interpolation ``params`` are appended in brackets so
    debugging context survives.
    """
    human = _humanise_key(key)
    if not params:
        return human
    formatted_params = ", ".join(f"{k}={v}" for k, v in sorted(params.items()))
    return f"{human} ({formatted_params})"


# ── Module-level singleton & convenience API ────────────────────────────────

_default_bundle = MessageBundle()


def translate(key: str, locale: str = DEFAULT_LOCALE, **params: Any) -> str:
    """Resolve a validation-message key for the given locale.

    Thin wrapper around the module-level :class:`MessageBundle` singleton so
    rule code can ``from app.core.validation.messages import translate``.
    """
    return _default_bundle.translate(key, locale=locale, **params)


def is_key_present(key: str, locale: str = DEFAULT_LOCALE) -> bool:
    """Return ``True`` iff ``key`` is defined in ``locale`` (no fallback)."""
    return _default_bundle.is_key_present(key, locale)


def available_locales() -> list[str]:
    """List locales currently loaded into the bundle."""
    return _default_bundle.available_locales()


def reload_bundle() -> None:
    """Force a cache refresh - primarily used by tests."""
    _default_bundle.reload()


def get_default_bundle() -> MessageBundle:
    """Return the module-level singleton (useful in tests)."""
    return _default_bundle


__all__ = [
    "DEFAULT_LOCALE",
    "MessageBundle",
    "available_locales",
    "get_default_bundle",
    "is_key_present",
    "reload_bundle",
    "translate",
]
