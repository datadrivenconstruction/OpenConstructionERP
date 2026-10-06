# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ importers package - pluggable per-format parsers.

Epic I (Leistungsverzeichnis / international BOQ) splits the historical
monolithic ``router.py`` import handlers into a discoverable registry of
parsers. Every importer implements :class:`BOQImporter` (see ``_base``);
the dispatcher reads the first 4 KB of the upload and walks the registry
calling ``detect()`` until one claims the file. The first match wins,
``parse()`` produces an :class:`ImportedBOQ`, the route persists rows
and triggers the configured ``rule_packs`` against the freshly imported
BOQ.

Concrete importers are added by successive commits in this wave:

* :mod:`gaeb_xml` - DACH GAEB DA XML 3.3 (X81/X83/X84/X86)
* :mod:`excel` - generic Excel/CSV with NRM + MasterFormat heuristics
* :mod:`bc3` - FIEBDC-3 (Spain + LATAM)
* :mod:`xpwe` - XPWE, the Italian estimating XML (computo metrico)

The dispatcher endpoint (``POST /boqs/{boq_id}/import/auto/``) iterates
``REGISTERED_IMPORTERS`` in order; for ambiguous files (e.g. a generic
Excel with no recognisable column headers) it falls back to the existing
``smart_import`` LLM path.
"""

from __future__ import annotations

from app.modules.boq.importers._base import (
    BOQImporter,
    ImportedBOQ,
    ImportedPosition,
    ImporterParseError,
)

# Ordered registry - first detect() match wins. Populated lazily as each
# importer module is registered (see :func:`_register_default_importers`).
REGISTERED_IMPORTERS: list[type[BOQImporter]] = []


def _register_default_importers() -> None:
    """Import + register the in-tree importers.

    Done inside a function so individual importer modules can be added
    in successive commits without breaking the package import on a
    partial checkout.
    """
    global REGISTERED_IMPORTERS

    importers: list[type[BOQImporter]] = []
    # GAEB XML - DACH (precise: starts with ``<GAEB``).
    try:
        from app.modules.boq.importers.gaeb_xml import GAEBXMLImporter

        importers.append(GAEBXMLImporter)
    except ImportError:
        pass
    # BC3 - Spain/LATAM (precise: starts with ``~V``).
    try:
        from app.modules.boq.importers.bc3 import BC3Importer

        importers.append(BC3Importer)
    except ImportError:
        pass
    # XPWE - Italian estimating XML (precise: ``<PweDocumento`` root). Also
    # claims the native project file only to refuse it with what to do.
    try:
        from app.modules.boq.importers.xpwe import XpweImporter

        importers.append(XpweImporter)
    except ImportError:
        pass
    # Excel/CSV - generic catch-all before LLM fallback.
    try:
        from app.modules.boq.importers.excel import ExcelImporter

        importers.append(ExcelImporter)
    except ImportError:
        pass

    REGISTERED_IMPORTERS = importers


_register_default_importers()


__all__ = [
    "BOQImporter",
    "ImportedBOQ",
    "ImportedPosition",
    "ImporterParseError",
    "REGISTERED_IMPORTERS",
]
