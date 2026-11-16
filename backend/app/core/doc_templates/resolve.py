# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which wording a document uses: one function, no database.

Order for a document in locale ``L``:

1. the firm's published text in ``L``;
2. the firm's published text in its primary language (the language it first
   customised the kind in), flagged ``doctpl.locale_fallback`` so the editor
   shows "no translation" (founder decision 16.11.2026: the firm's own wording
   wins over platform text in another language);
3. the built-in wording in ``L``, else English.

Inside a published text an empty block takes the built-in block, and a text
that fails validation is not used at all (built-in wording, issue logged):
rendering never raises to the reader.
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field

from app.core.doc_templates.registry import DocumentKind
from app.core.doc_templates.rules import LOCALE_FALLBACK, Issue, check_blocks, has_errors

__all__ = ["Published", "ResolvedText", "normalise_locale", "resolve_text"]

logger = logging.getLogger(__name__)


def normalise_locale(value: str | None) -> str:
    """``de-AT`` / ``DE`` / ``None`` -> ``de`` / ``de`` / ``en``."""
    primary = (value or "").strip().lower().replace("_", "-").split("-")[0]
    return primary if primary.isalpha() and 2 <= len(primary) <= 3 else "en"


@dataclass(frozen=True)
class Published:
    """A published version as the resolver needs it."""

    version_id: uuid.UUID | None
    blocks: Mapping[str, str]


@dataclass
class ResolvedText:
    """The wording a document prints, and where it came from.

    ``source`` is ``published``, ``primary_language`` or ``default``.
    """

    kind: DocumentKind
    locale: str
    blocks: dict[str, str]
    source: str
    version_id: uuid.UUID | None = None
    text_locale: str = "en"
    warnings: list[Issue] = field(default_factory=list)


def _usable(kind: DocumentKind, pub: Published | None) -> bool:
    if pub is None or not any((v or "").strip() for v in pub.blocks.values()):
        return False
    issues = check_blocks(kind, {k: v for k, v in pub.blocks.items() if k in kind.blocks})
    if has_errors(issues):
        logger.warning(
            "doc_templates: published %s version %s has errors, built-in text used", kind.key, pub.version_id
        )
        return False
    return True


def resolve_text(
    kind: DocumentKind,
    locale: str | None,
    published: Mapping[str, Published],
    primary_locale: str | None = None,
) -> ResolvedText:
    """Resolve the blocks of *kind* for a document in *locale*.

    Args:
        kind: The registered kind.
        locale: The document language (already chosen by the generator).
        published: Published versions of the firm's templates by locale.
        primary_locale: The firm's primary language for this kind, if any.
    """
    lang = normalise_locale(locale)
    defaults = kind.default_blocks(lang)
    candidates: list[tuple[str, str]] = [(lang, "published")]
    if primary_locale and normalise_locale(primary_locale) != lang:
        candidates.append((normalise_locale(primary_locale), "primary_language"))
    for text_locale, source in candidates:
        pub = published.get(text_locale)
        if not _usable(kind, pub):
            continue
        assert pub is not None
        own_defaults = defaults if text_locale == lang else kind.default_blocks(text_locale)
        blocks: dict[str, str] = {}
        for b in kind.blocks:
            own = pub.blocks.get(b) or ""
            blocks[b] = own if own.strip() else own_defaults.get(b, "")
        warnings = []
        if source == "primary_language":
            warnings.append(Issue(LOCALE_FALLBACK, "warning", "", {"language": lang, "fallback": text_locale}))
        return ResolvedText(kind, lang, blocks, source, pub.version_id, text_locale, warnings)
    return ResolvedText(kind, lang, defaults, "default", None, lang if lang in kind.languages else "en")
