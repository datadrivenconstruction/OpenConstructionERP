# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What a module declares so its document can be laid out by the firm.

A :class:`LayoutSpec` names the document's merge fields, its collections (the
line item tables) with the columns a table may show, the record sections the
module draws itself (a supplier confirmation, a list of rejections), what may
never be hidden, and the standard template that reproduces the module's
hand-written form. A :class:`LayoutContext` is one record's data for it,
already formatted in the document language. The engine composes the two.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from app.core.doc_templates.registry import MandatoryField, MergeField

__all__ = [
    "COLUMN_FORMATS",
    "COMMON_FIELDS",
    "CollectionSpec",
    "ColumnSpec",
    "LayoutContext",
    "LayoutSpec",
    "SectionSpec",
    "all_layouts",
    "get_layout",
    "register_layout",
    "unregister_layout",
]

#: How a column or computed value is written: as stored text, or formatted in the document language.
COLUMN_FORMATS: tuple[str, ...] = ("text", "money", "quantity", "number", "percent", "date", "index")


#: Fields every layout offers: the project, the issuing company (company profile) and the print time.
COMMON_FIELDS: tuple[MergeField, ...] = (
    MergeField("project.name", "text", "Riverside Block B", "project"),
    MergeField("project.code", "text", "RB-B", "project"),
    MergeField("project.label", "text", "Riverside Block B (RB-B)", "project"),
    MergeField("entity.legal_name", "text", "Muster Bau GmbH", "company"),
    MergeField("entity.address", "text", "Hauptstr. 1, 10115 Berlin", "company"),
    MergeField("entity.registration_line", "text", "HRB 12345, Amtsgericht Berlin", "company"),
    MergeField("entity.vat_id", "text", "DE123456789", "company"),
    MergeField("entity.tax_number", "text", "", "company"),
    MergeField("entity.tax_id", "text", "DE123456789", "company"),
    MergeField("entity.email", "text", "info@example.com", "company"),
    MergeField("entity.phone", "text", "+49 30 000000", "company"),
    MergeField("entity.website", "url", "https://example.com", "company"),
    MergeField("doc.generated", "text", "2026-11-18 09:30 UTC", "document"),
)


@dataclass(frozen=True)
class ColumnSpec:
    """A column a table bound to a collection may show.

    Attributes:
        id: Key of the value in each row (``description``).
        label: English heading; the document heading comes from the context.
        format: One of :data:`COLUMN_FORMATS`.
        required: The column may not be hidden (a standard or a pack says so).
        right: Numbers, right aligned.
        weight: Share of the slack width (see ``table_layout``).
        keep: Never wraps (numbers, dates, codes).
        source: The standard behind ``required``.
    """

    id: str
    label: str
    format: str = "text"
    required: bool = False
    right: bool = False
    weight: float = 1.0
    keep: bool = False
    source: str = ""


@dataclass(frozen=True)
class CollectionSpec:
    """Rows of the record a table can list (``items`` of a purchase order)."""

    id: str
    label: str
    columns: tuple[ColumnSpec, ...]

    def column(self, column_id: str) -> ColumnSpec | None:
        """The column declared under *column_id*."""
        return next((c for c in self.columns if c.id == column_id), None)


@dataclass(frozen=True)
class SectionSpec:
    """A part of the document: either drawn by the module (``builtin``) or a standard block.

    Attributes:
        id: Block id in the standard template, or the module's section id.
        label: English name shown in the editor.
        required: May not be hidden or deleted.
        builtin: Drawn by the module from the record (not configurable beyond title and place).
        source: Why it is required (``EN 16931``, ``Platform standard``).
    """

    id: str
    label: str
    required: bool = False
    builtin: bool = False
    source: str = ""


@dataclass
class LayoutContext:
    """One record's data for a layout, already formatted in the document language.

    Attributes:
        locale: The document language.
        values: Display value per merge field path.
        raw: Raw value per merge field path (``Decimal``, ``str``, ``None``) for conditions and expressions.
        labels: Default wording in the document language: ``title``, ``subject``,
            ``field:<path>``, ``column:<collection>.<id>``, ``section:<id>``,
            ``signer:<path>``, ``status:<code>``.
        collections: Rows per collection; each row maps column id to ``(raw, display)``.
        sections: The module's own rendering of each builtin section (record form blocks).
        base: The record form skeleton (title, number, project, status, subject, footer wording).
        status: Raw status code of the record, for the status watermark.
        format: ``(format, raw) -> display`` in the document's number style.
        signature_rows: ``[(role, name)] -> rows`` of the signature block, header first.
        project_id: Owning project, for access checks and the project override.
        filename: Download name.
        empty: What an absent value prints as.
    """

    locale: str
    values: dict[str, str]
    raw: dict[str, Any]
    labels: dict[str, str]
    collections: dict[str, list[dict[str, tuple[Any, str]]]]
    sections: dict[str, list[Any]]
    base: Any
    status: str = ""
    format: Callable[[str, Any], str] = field(default=lambda _fmt, value: "" if value is None else str(value))
    signature_rows: Callable[[Sequence[tuple[str, str]]], list[list[str]]] = field(
        default=lambda signers: [["", "", "", ""], *[[r, n, "", ""] for r, n in signers]]
    )
    project_id: Any = None
    filename: str = "document.pdf"
    empty: str = "-"


#: ``(session, record id, locale) -> LayoutContext``; raises ``LookupError`` when the record is gone.
ContextFn = Callable[[Any, str, str], Awaitable[LayoutContext]]
#: ``(session, project ids or None) -> [(record id, label)]``.
RecordsFn = Callable[[Any, "set[Any] | None"], Awaitable[list[tuple[str, str]]]]


@dataclass(frozen=True)
class LayoutSpec:
    """A document whose structure, wording and look a firm can lay out.

    Attributes:
        key: Stable id ``<module>.<document>``.
        module: Owning module directory name.
        label: English name; the UI translates ``doc_templates.kind.<key>``.
        appearance_type: Per-type look key in ``pdf_appearance.DOCUMENT_TYPES``.
        fields: Merge fields with sample values.
        collections: Tables the document can list.
        sections: Sections of the standard template (builtin and standard blocks).
        statuses: Record status codes, for the watermark by status.
        standard: ``(legacy hidden sections or None) -> template``: the standard template.
        context: Builds one record's context.
        sample: Builds a context from sample data, for a preview without a record.
        records: Lists records "Preview with" can use.
        mandatory: Data the document may not be issued without.
        languages: Languages the module's built-in wording exists in.
        locked_fields: Fields of fields blocks that may not be removed, with the source.
    """

    key: str
    module: str
    label: str
    fields: tuple[MergeField, ...]
    collections: tuple[CollectionSpec, ...]
    sections: tuple[SectionSpec, ...]
    standard: Callable[[Mapping[str, bool] | None], dict[str, Any]]
    sample: Callable[[str], LayoutContext]
    context: ContextFn | None = field(default=None, compare=False)
    records: RecordsFn | None = field(default=None, compare=False)
    appearance_type: str | None = None
    statuses: tuple[str, ...] = ()
    mandatory: tuple[MandatoryField, ...] = ()
    languages: tuple[str, ...] = ("en",)
    locked_fields: Mapping[str, str] = field(default_factory=dict)

    @property
    def field_paths(self) -> frozenset[str]:
        """Every declared merge field, plus the page counter."""
        return frozenset({f.path for f in self.fields} | {"page.number", "page.total"})

    def collection(self, collection_id: str) -> CollectionSpec | None:
        """The collection declared under *collection_id*."""
        return next((c for c in self.collections if c.id == collection_id), None)

    def section(self, section_id: str) -> SectionSpec | None:
        """The section declared under *section_id*."""
        return next((s for s in self.sections if s.id == section_id), None)


_LAYOUTS: dict[str, LayoutSpec] = {}
_PROVIDERS: list[Callable[[], None]] = []


def register_layout(spec: LayoutSpec) -> LayoutSpec:
    """Register (or replace) a layout. Idempotent per key."""
    _LAYOUTS[spec.key] = spec
    return spec


def unregister_layout(key: str) -> None:
    """Forget a layout (module uninstalled, tests)."""
    _LAYOUTS.pop(key, None)


def register_layout_provider(provider: Callable[[], None]) -> None:
    """Register a callable that registers layouts lazily, on the first read."""
    if provider not in _PROVIDERS:
        _PROVIDERS.append(provider)


def _run_providers() -> None:
    while _PROVIDERS:
        provider = _PROVIDERS.pop(0)
        try:
            provider()
        except Exception:  # noqa: BLE001 - one broken module must not hide every other document
            import logging

            logging.getLogger(__name__).warning("doc_templates: layout provider failed", exc_info=True)


def get_layout(key: str) -> LayoutSpec | None:
    """The layout registered under *key*, or ``None``."""
    _run_providers()
    return _LAYOUTS.get(key)


def all_layouts() -> list[LayoutSpec]:
    """Every registered layout, ordered by module and key."""
    _run_providers()
    return sorted(_LAYOUTS.values(), key=lambda s: (s.module, s.key))
