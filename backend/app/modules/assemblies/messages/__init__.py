# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Module-local message bundle of the assemblies component-tax rules.

English is the source; a locale without a file here is answered in English by
the shared :class:`~app.core.validation.messages.MessageBundle` fallback.
"""

from __future__ import annotations

from pathlib import Path

from app.core.validation.messages import MessageBundle

_bundle = MessageBundle(messages_dir=Path(__file__).parent)


def translate(key: str, locale: str = "en", **params: object) -> str:
    """Resolve an assemblies message key for ``locale`` with ``str.format`` params."""
    return _bundle.translate(key, locale=locale, **params)
