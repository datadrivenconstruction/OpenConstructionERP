# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Registry of national party identifiers (tax numbers, company and person registers).

Each country lives in its own sibling module (``fr.py``, ``pl.py``, ``eg.py`` ...) and
registers its schemes with :func:`register` at import time. This file only holds the
registry and the result type, so country modules can be added in parallel without
touching it. Modules are discovered automatically on first lookup.

A validator receives the raw value and returns an :class:`IdentifierCheck`. It must
not raise on bad input: an unknown or malformed value is a result, not an exception.
"""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from dataclasses import dataclass, field

__all__ = ["IdentifierCheck", "Validator", "check", "register", "schemes_for"]


@dataclass(frozen=True)
class IdentifierCheck:
    """Outcome of validating one identifier value."""

    valid: bool
    normalised: str
    scheme: str
    country: str
    reason: str | None = None
    source: str | None = None
    details: dict[str, str] = field(default_factory=dict)


Validator = Callable[[str], IdentifierCheck]

_REGISTRY: dict[tuple[str, str], Validator] = {}
_LOADED = False


def register(country: str, scheme: str) -> Callable[[Validator], Validator]:
    """Register ``fn`` as the validator for ``(country, scheme)``.

    Args:
        country: ISO 3166-1 alpha-2 code, upper case.
        scheme: Scheme id in lower snake case, e.g. ``"siren"``, ``"nip"``, ``"rin"``.
    """

    key = (country.upper(), scheme.lower())

    def decorator(fn: Validator) -> Validator:
        if key in _REGISTRY and _REGISTRY[key] is not fn:
            raise ValueError(f"identifier scheme already registered: {key}")
        _REGISTRY[key] = fn
        return fn

    return decorator


def _load_country_modules() -> None:
    global _LOADED
    if _LOADED:
        return
    for info in pkgutil.iter_modules(__path__):
        if not info.name.startswith("_"):
            importlib.import_module(f"{__name__}.{info.name}")
    _LOADED = True


def schemes_for(country: str) -> list[str]:
    """Return the scheme ids registered for ``country``, sorted."""

    _load_country_modules()
    code = country.upper()
    return sorted(scheme for (c, scheme) in _REGISTRY if c == code)


def check(country: str, scheme: str, value: str) -> IdentifierCheck | None:
    """Validate ``value`` against ``(country, scheme)``.

    Returns None when no validator is registered, so callers can tell
    "not checked" apart from "checked and invalid".
    """

    _load_country_modules()
    fn = _REGISTRY.get((country.upper(), scheme.lower()))
    return fn(value) if fn is not None else None
