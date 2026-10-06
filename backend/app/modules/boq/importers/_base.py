# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ importer Protocol + transport dataclasses.

Defines the contract every BOQ importer must satisfy:

1. ``detect(head_bytes, filename) -> bool`` - cheap, magic-byte/extension
   sniff against the first ~4 KB of the upload. Must NEVER raise; must
   NEVER read past the supplied head bytes.
2. ``parse(content, *, locale='en') -> ImportedBOQ`` - full parse. May
   raise ``ImportError`` (we re-export :class:`ImporterParseError`) to
   surface a user-safe 400.

The dispatcher route is free to persist the returned positions via
``BOQService.add_position``; importers themselves are pure (no DB I/O),
which keeps them testable in isolation against synthetic fixtures.

Every importer also advertises:

* ``format_id`` - stable identifier (``"gaeb_xml"``, ``"bc3"``, ``"excel"``).
* ``extensions`` - tuple of lowercased extensions (``(".xlsx", ".csv")``).
* ``display_name`` - i18n-key-friendly human label.
* ``rule_packs`` - validation rule packs to fire after import (e.g.
  ``("gaeb", "din276", "boq_quality")``). The dispatcher unions this
  with the project's configured ``REGION_RULES`` so DACH projects still
  pick up DIN 276 on an Excel import.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Protocol, runtime_checkable


class ImporterParseError(ValueError):
    """Raised by an importer's ``parse()`` when the bytes can't be turned
    into positions. The dispatcher translates this into HTTP 400 - the
    message must be user-safe (no stack traces, no internal paths).

    ``code`` names the failure and ``params`` carries the values its wording
    needs: the import dialog words it in the reader's language from
    ``boq.import_error.<code>``. The message is the English fallback for
    logs and for a client that does not know the code. Every raise in the
    importers passes a code; a test walks them and checks the frontend
    has a wording for each.
    """

    def __init__(self, message: str, *, code: str = "import_parse_failed", params: dict[str, Any] | None = None):
        super().__init__(message)
        self.code = code
        self.params: dict[str, Any] = dict(params or {})

    def as_detail(self) -> dict[str, Any]:
        """The 400 body's ``detail``: the code, its values and the English fallback."""
        return {"code": self.code, "params": self.params, "message": str(self)}


def xml_error_position(exc: BaseException) -> dict[str, int]:
    """Where an XML parser stopped, as the ``line`` and ``column`` a parse error's wording names."""
    position = getattr(exc, "position", None)
    if isinstance(position, tuple) and len(position) == 2:
        return {"line": int(position[0]), "column": int(position[1])}
    return {}


@dataclass(slots=True)
class ImportedPosition:
    """One BOQ row extracted by an importer.

    The fields intentionally mirror :class:`PositionCreate` so the
    dispatcher route can do a direct ``PositionCreate(**asdict(row))``
    without a translation layer. ``classification`` and ``metadata`` are
    plain dicts (no ``JSONB`` typing) because importers are sync and
    don't touch the DB.

    ``ordinal`` may be left blank - the dispatcher will auto-number any
    blank ordinals before persisting (consistent with the historical
    Excel/CSV behaviour).
    """

    description: str
    ordinal: str = ""
    unit: str = "pcs"
    quantity: float = 0.0
    unit_rate: float = 0.0
    classification: dict[str, Any] = field(default_factory=dict)
    source: str = "manual"
    metadata: dict[str, Any] = field(default_factory=dict)
    # Optional: a section header row (no quantity, no rate). The
    # dispatcher persists these with ``unit="section"``.
    is_section: bool = False
    # Round-trip identity (GitHub #360). Populated only by the Excel/CSV
    # importer when the sheet carries the dedicated "Position ID" column an
    # export stamped. Blank / absent -> a new row; a value that belongs to
    # the target BOQ -> update in place. Every other importer leaves it
    # ``None`` (all-create, unchanged behaviour).
    position_id: str | None = None


@dataclass(slots=True)
class ImportedBOQ:
    """Aggregate result of one importer parse.

    The dispatcher reads ``positions`` row-by-row and persists each via
    ``BOQService.add_position``. ``metadata`` and ``warnings`` flow back
    into the import response so the UI can render currency, section
    counts, parser-specific notes etc.
    """

    positions: list[ImportedPosition] = field(default_factory=list)
    # Number of rows the importer intentionally skipped (e.g. blank
    # description rows, "Total" footer rows). Pure diagnostic - the
    # dispatcher echoes this back to the client.
    skipped: int = 0
    # Per-row errors that did not abort the import. Each entry is a
    # ``{"ordinal": str, "error": str}`` dict for UI rendering.
    errors: list[dict[str, Any]] = field(default_factory=list)
    # Soft warnings (e.g. "unit rate is 10× the median").
    warnings: list[dict[str, Any]] = field(default_factory=list)
    # Free-form metadata for round-trip export / UI rendering.
    metadata: dict[str, Any] = field(default_factory=dict)
    # Source format token (``"gaeb"``, ``"bc3"``, ``"xlsx"``, ``"csv"``)
    # - surfaced in the import response as ``source_format``.
    source_format: str = ""
    # Currency captured from the source file (GAEB ``<Cur>``, BC3 ``DC``
    # record). Empty if the source did not carry one.
    currency: str = ""
    # The rows are in tree order (every section before the rows filed under
    # it, a section's own items before its sub-sections) and every item names
    # its section, so persistence may write them in one batch instead of one
    # row at a time. Off by default: a flat sheet relies on the per-row path.
    document_order: bool = False


@runtime_checkable
class BOQImporter(Protocol):
    """The contract every BOQ importer in :mod:`importers` must satisfy.

    See module docstring for the full protocol description. Implementers
    are stateless ``@classmethod``-only classes; the dispatcher never
    instantiates them.
    """

    format_id: ClassVar[str]
    extensions: ClassVar[tuple[str, ...]]
    display_name: ClassVar[str]
    rule_packs: ClassVar[tuple[str, ...]]

    @classmethod
    def detect(cls, head_bytes: bytes, filename: str) -> bool:
        """Return ``True`` iff this importer can parse the upload.

        MUST NOT raise. MUST NOT read past ``head_bytes``.
        """
        ...

    @classmethod
    async def parse(cls, content: bytes, *, locale: str = "en") -> ImportedBOQ:
        """Parse the full upload. Raise :class:`ImporterParseError` for
        user-safe error messages, any other exception is logged + masked.
        """
        ...
