# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The per-document KSeF marker of the JPK_V7(3) records.

From the February 2026 periods every sales and purchase record in JPK_V7M and
JPK_V7K carries the document's KSeF number, or, when it has none, exactly one
marker: OFF, BFK or DI. The platform has no JPK_V7 export yet; this is the piece
that export will need, so the marker is decided in one place and from the same
data the clearance module already holds.

Which marker applies to which way of issuing is a table in
:data:`facts.JPK_MARKERS`. One row there (offline24) is marked for expert review
because the sources disagree.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.modules.einvoice_ksef import ksef_number
from app.modules.einvoice_ksef.facts import JPK_MARKERS

ISSUED_OUTSIDE_KSEF = "outside_ksef"
NOT_AN_INVOICE = "not_an_invoice"


@dataclass(frozen=True)
class JpkMarker:
    # The KSeF number, when there is one; then ``marker`` is empty.
    ksef_number: str
    marker: str
    needs_expert_review: bool = False
    reason: str = ""


def marker_for(*, ksef_number_value: str = "", issued_as: str = "", is_invoice: bool = True) -> JpkMarker:
    """The JPK_V7(3) entry for one document.

    Args:
        ksef_number_value: The document's KSeF number, if it has one.
        issued_as: How it was issued when it has none: an offline mode key, or
            ``outside_ksef`` for an invoice that never went through KSeF.
        is_invoice: False for a document that is not an invoice (internal
            document, customs declaration, cash-register report).
    """
    if not is_invoice:
        row = JPK_MARKERS[NOT_AN_INVOICE]
        return JpkMarker("", row.marker, row.needs_expert_review, "not an invoice")
    number = (ksef_number_value or "").strip()
    if number:
        if not ksef_number.is_valid(number):
            raise ValueError(f"{number!r} is not a valid KSeF number: {'; '.join(ksef_number.problems(number))}")
        return JpkMarker(number, "", False, "the document has a KSeF number")
    key = (issued_as or ISSUED_OUTSIDE_KSEF).strip().lower()
    row = JPK_MARKERS.get(key)
    if row is None:
        raise ValueError(f"{issued_as!r} is not a known way of issuing; use an offline mode or {ISSUED_OUTSIDE_KSEF}")
    return JpkMarker("", row.marker, row.needs_expert_review, row.notes or f"issued as {key}")


__all__ = ["ISSUED_OUTSIDE_KSEF", "NOT_AN_INVOICE", "JpkMarker", "marker_for"]
