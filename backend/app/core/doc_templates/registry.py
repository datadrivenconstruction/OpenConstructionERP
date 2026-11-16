# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Registry of document kinds: every PDF and email whose wording a firm can change.

A module registers a :class:`DocumentKind` (usually from its ``on_startup``):
its key, channel, editable blocks, merge fields with a sample value each and a
function returning the built-in wording per language. Modules that are not part
of the core tree (framework call-off orders, sealed estimate certificates) use
the same :func:`register_kind`; a kind whose module is not installed simply
never registers, so it never shows.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "EMAIL_BLOCKS",
    "FIELD_TYPES",
    "PDF_BLOCKS",
    "DocumentKind",
    "MandatoryField",
    "MergeField",
    "RecordDocument",
    "all_kinds",
    "get_kind",
    "register_kind",
    "register_kind_provider",
    "unregister_kind",
]

PDF_BLOCKS: tuple[str, ...] = ("title", "intro", "body", "closing", "terms", "signature", "footer")
EMAIL_BLOCKS: tuple[str, ...] = ("subject", "preheader", "body", "cta_label", "footer")
FIELD_TYPES: tuple[str, ...] = ("text", "date", "money", "quantity", "url")
FIELD_GROUPS: tuple[str, ...] = ("project", "document", "company", "recipient", "sender")

#: ``(blocks, locale, values) -> (bytes, media type)``; renders a preview with the real generator.
PreviewFn = Callable[[Mapping[str, str], str, Mapping[str, str]], tuple[bytes, str]]
#: ``(session, project_ids or None for all) -> [(record id, label)]``: records a preview can use.
RecordsFn = Callable[[Any, "set[Any] | None"], Awaitable[list[tuple[str, str]]]]
#: ``(session, record id, blocks, locale) -> (bytes, media type, project id)``: real-record preview.
RecordPreviewFn = Callable[[Any, str, Mapping[str, str], str], Awaitable[tuple[bytes, str, Any]]]


@dataclass(frozen=True)
class MergeField:
    """A value the generator supplies, e.g. ``package.name``.

    Attributes:
        path: Dotted lower-case name used as ``{{path}}``.
        type: One of :data:`FIELD_TYPES`; the generator formats it in the document locale.
        sample: Value shown in the picker and used by the sample preview.
        group: Picker group, one of :data:`FIELD_GROUPS`.
    """

    path: str
    type: str = "text"
    sample: str = ""
    group: str = "document"


@dataclass(frozen=True)
class MandatoryField:
    """Data a document may not be issued without, e.g. the seller's tax id on an invoice.

    Attributes:
        paths: Field paths; any one of them filled satisfies the requirement.
        label: English name shown in the issue (``{{field}}``).
        source: The standard or law that asks for it (``EN 16931``).
        where: Where the user fills it in (``company profile``, ``invoice``).
    """

    paths: tuple[str, ...]
    label: str
    source: str
    where: str = ""


@dataclass
class RecordDocument:
    """Everything a generic document PDF needs from one record, already formatted.

    Attributes:
        values: Merge values by field path, formatted in the document locale.
        meta: Label/value rows under the title.
        table: Item table, if any (an :class:`app.core.doc_templates.pdf.TableSpec`).
        totals: Label/value rows under the table.
        project_id: Owning project, for access checks and the issue log.
        filename: Download name without extension.
        locale: The document language the record asks for, if it has one.
    """

    values: dict[str, str]
    meta: list[tuple[str, str]] = field(default_factory=list)
    table: Any = None
    totals: list[tuple[str, str]] = field(default_factory=list)
    project_id: Any = None
    filename: str = "document"
    locale: str | None = None


#: ``(session, record id, locale) -> RecordDocument``; raises LookupError when the record is gone.
RecordDocumentFn = Callable[[Any, str, str], Awaitable[RecordDocument]]


@dataclass(frozen=True)
class DocumentKind:
    """A registered document or email.

    Attributes:
        key: Stable id ``<module>.<document>``.
        channel: ``pdf`` or ``email``.
        module: Owning module directory name (``tendering``), used for grouping and visibility.
        label: English display name; the UI translates ``doc_templates.kind.<key>``.
        blocks: Editable blocks, a subset of :data:`PDF_BLOCKS` or :data:`EMAIL_BLOCKS`.
        fields: Merge fields the generator fills.
        defaults: ``locale -> {block: text}`` built-in wording; ``{}`` for an unshipped language.
        languages: Languages with built-in wording; ``en`` must be one.
        required_blocks: Blocks that may not be left empty.
        preview: Optional renderer through the real generator.
        appearance_type: Key in :data:`app.core.pdf_appearance.DOCUMENT_TYPES`, if any.
        records: Optional lister of real records for "Preview with".
        record_preview: Optional renderer of the draft against one real record.
        mandatory: Data the document may not be issued without (standards, not country law).
        record_document: Optional builder of a generic document PDF from one record;
            kinds with it can be issued through ``/doc-templates/{kind}/records/{id}/pdf``.
    """

    key: str
    channel: str
    module: str
    label: str
    blocks: tuple[str, ...]
    fields: tuple[MergeField, ...]
    defaults: Callable[[str], Mapping[str, str]]
    languages: tuple[str, ...] = ("en",)
    required_blocks: tuple[str, ...] = ()
    preview: PreviewFn | None = field(default=None, compare=False)
    appearance_type: str | None = None
    records: RecordsFn | None = field(default=None, compare=False)
    record_preview: RecordPreviewFn | None = field(default=None, compare=False)
    mandatory: tuple[MandatoryField, ...] = ()
    record_document: RecordDocumentFn | None = field(default=None, compare=False)

    @property
    def field_paths(self) -> frozenset[str]:
        """Every declared field path."""
        return frozenset(f.path for f in self.fields)

    def samples(self) -> dict[str, str]:
        """Sample values for a preview without a record."""
        return {f.path: f.sample for f in self.fields}

    def default_blocks(self, locale: str | None) -> dict[str, str]:
        """Built-in wording in *locale*, else English, restricted to the kind's blocks."""
        primary = (locale or "en").strip().lower().split("-")[0] or "en"
        raw: Mapping[str, str] = {}
        for lang in (primary, "en"):
            if lang in self.languages:
                try:
                    raw = self.defaults(lang) or {}
                except Exception:  # noqa: BLE001 - a broken catalogue must not break rendering
                    raw = {}
                if raw:
                    break
        return {b: str(raw.get(b, "") or "") for b in self.blocks}


_REGISTRY: dict[str, DocumentKind] = {}
_PROVIDERS: list[Callable[[], None]] = []


def register_kind(kind: DocumentKind) -> DocumentKind:
    """Register (or replace) a kind. Idempotent per key.

    Raises:
        ValueError: on an unknown channel, block or field type, or no English default.
    """
    allowed = PDF_BLOCKS if kind.channel == "pdf" else EMAIL_BLOCKS if kind.channel == "email" else None
    if allowed is None:
        raise ValueError(f"{kind.key}: unknown channel {kind.channel!r}")
    bad = [b for b in kind.blocks if b not in allowed]
    if bad:
        raise ValueError(f"{kind.key}: blocks {bad} not allowed for {kind.channel}")
    if any(f.type not in FIELD_TYPES for f in kind.fields):
        raise ValueError(f"{kind.key}: unknown field type")
    if "en" not in kind.languages:
        raise ValueError(f"{kind.key}: built-in English wording is required")
    _REGISTRY[kind.key] = kind
    return kind


def unregister_kind(key: str) -> None:
    """Forget a kind (module uninstalled, tests)."""
    _REGISTRY.pop(key, None)


def register_kind_provider(provider: Callable[[], None]) -> None:
    """Register a callable that registers kinds lazily, on the first registry read."""
    if provider not in _PROVIDERS:
        _PROVIDERS.append(provider)


def _run_providers() -> None:
    while _PROVIDERS:
        provider = _PROVIDERS.pop(0)
        try:
            provider()
        except Exception:  # noqa: BLE001 - one broken module must not hide every other kind
            import logging

            logging.getLogger(__name__).warning("doc_templates: kind provider failed", exc_info=True)


def get_kind(key: str) -> DocumentKind | None:
    """The kind registered under *key*, or ``None``."""
    _run_providers()
    return _REGISTRY.get(key)


def all_kinds() -> list[DocumentKind]:
    """Every registered kind, ordered by channel, module and key."""
    _run_providers()
    return sorted(_REGISTRY.values(), key=lambda k: (k.channel, k.module, k.key))
