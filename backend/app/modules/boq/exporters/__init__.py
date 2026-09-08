# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""BOQ budget exporters (canonical BOQ -> external interchange formats).

The mirror of :mod:`app.modules.boq.importers`: each exporter turns a
``BOQWithSections`` into a downloadable interchange file. The FIEBDC-3 /
BC3 writer lives here as a module; the GAEB DA XML and spreadsheet
writers are still inline in ``router.py`` and may migrate here over time.

Whether a writer lives in this package or inline in the router, it is
listed once in :data:`REGISTERED_EXPORTERS`. The list exists so that the
question "can this product write format X" has exactly one answer that a
caller can read, instead of the answer being spread across five route
handlers and inferred by whoever is looking.

The import side already answers that question through
``REGISTERED_IMPORTERS``, whose members advertise a ``format_id``. Export
had no equivalent, so a screen offering the user a choice of formats had
no way to ask and would have had to carry its own copy of the list. A
second copy of a list like this drifts: the day someone adds a writer,
the copy still says four formats and nobody notices, because nothing
fails.

Each entry names the route that serves it. That is deliberately the
weakest part of the record, being a string rather than a reference, so
``tests/unit/test_exchange_format_catalogue_cannot_promise_more_than_the_code_does.py`` resolves every ``route``
against the assembled application's real route table. An entry for a
route that does not exist fails there rather than in front of a user who
clicked it.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.boq.exporters.bc3 import build_bc3


@dataclass(frozen=True, slots=True)
class BOQExporter:
    """One direction the product can write a BOQ out in.

    ``format_id`` is the same vocabulary the importers use, so a format
    that can be both read and written carries one identifier on both
    sides and a caller can join them. ``gaeb_xml`` and ``bc3`` and
    ``excel`` appear on both lists for exactly that reason; ``csv`` and
    ``pdf`` appear only here, because the product writes them and reads
    neither. (A CSV upload is read by the spreadsheet importer, whose
    ``format_id`` is ``excel``, so CSV is not a readable format in this
    vocabulary even though CSV files import fine.)
    """

    format_id: str
    #: Extension of the produced file, lowercased, leading dot.
    extension: str
    #: What the route sets as the response ``media_type``, without the
    #: charset parameter. Kept so a caller can label a download without
    #: issuing a request first.
    media_type: str
    #: Path under ``/boqs/{boq_id}/`` that serves this format. Verified
    #: against the real route table by the registry test.
    route: str
    #: True when the writer produces the format's own container. False
    #: when it produces a spreadsheet or a document that carries the
    #: information but is not the format's native file, which is a
    #: difference a user needs told before they send it to a client.
    native_container: bool = True


#: Every format this product can write today. Order is presentation
#: order for a caller that does not sort: interchange formats first,
#: then the general purpose ones.
REGISTERED_EXPORTERS: tuple[BOQExporter, ...] = (
    BOQExporter(
        format_id="gaeb_xml",
        extension=".x83",
        media_type="application/xml",
        route="export/gaeb",
    ),
    BOQExporter(
        format_id="bc3",
        extension=".bc3",
        media_type="text/plain",
        route="export/bc3",
    ),
    BOQExporter(
        format_id="excel",
        extension=".xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        route="export/excel",
    ),
    BOQExporter(
        format_id="csv",
        extension=".csv",
        media_type="text/csv",
        route="export/csv",
    ),
    BOQExporter(
        format_id="pdf",
        extension=".pdf",
        media_type="application/pdf",
        route="export/pdf",
    ),
)


def exporter_for(format_id: str) -> BOQExporter | None:
    """Return the writer for ``format_id``, or ``None`` if we have none."""
    for exporter in REGISTERED_EXPORTERS:
        if exporter.format_id == format_id:
            return exporter
    return None


__all__ = [
    "REGISTERED_EXPORTERS",
    "BOQExporter",
    "build_bc3",
    "exporter_for",
]
