# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""GAEB DA XML 3.3 X31, Mengenermittlung (quantity determination).

An X31 is the site's answer to the bill: per OZ, the quantity that was
measured, optionally with the REB 23.003 take-off rows behind it. It carries
no text and no prices (Fachdokumentation 3.3, 7.3: "a strongly reduced schema
on the basis of the 80 phases").

What this module does with one
------------------------------
**Export** writes the measured quantity of each position of a bill. The
measured quantity is the total of the position's measurement sheet
(``metadata.measurement``), the same figure the measurement drawer shows and
``reconcile`` compares against the bill quantity. On request the bill
quantity itself can be written instead.

Only the per-item total (``QtyDeterm/Qty``) is written, never take-off rows.
A REB row is an 80 character fixed-format record whose meaning depends on a
formula number from the REB 23.003 formula catalogue; our sheets are free
formulas, and writing them as REB rows would hand the receiver arithmetic
that its REB engine evaluates differently. The Fachdokumentation allows a
total without rows (7.3: "Die Gesamtsumme einer Position kann auch ohne
dazugehörende Aufmaßzeilen übertragen werden").

**Import** never writes anything. It reads the file, matches each OZ to a
position, and returns a proposal: the measured quantity per matched
position, next to what the position carries now, plus every OZ that matched
nothing, matched more than one position, or carried rows without a total.
A person confirms which proposals to apply, and the apply step is a separate
call. Following 7.3 for "applications without REB computation", the total
is what is read; the rows are kept for display and for the audit trail.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.boq.gaeb_common import (
    PositionIndex,
    append_bkdn,
    append_gaeb_info,
    dec,
    exchange_phase,
    iter_boq_items,
    mint_id,
    namespace_for,
    parse_xml,
    plan_oz_layout,
    q3,
    serialize,
    write_oz_body,
)
from app.modules.boq.importers._base import ImporterParseError
from app.modules.boq.importers.gaeb_xml import _find_child, _local, _text_of

#: ``QtyDetermInfo/MethodDescription`` is a closed list in the schema. The
#: 2009 edition is the one the Fachdokumentation names for X31 (the 2012
#: edition "does not apply to exchange via X31").
METHOD_REB_2009 = "REB23003-2009"

#: ``tgDecimal_11_3``: eleven digits, three of them decimals.
_QTY_LIMIT = Decimal("100000000")

#: Rows shown per item in a proposal. A long Aufmaß can carry hundreds of rows
#: per position; the proposal is for a person to read, the count says the rest.
MAX_ROWS_PER_ITEM = 50


# ── Export ───────────────────────────────────────────────────────────────


@dataclass(slots=True)
class X31Export:
    """A written X31 and an account of what did not go into it."""

    xml: str
    written: list[str]
    skipped: list[dict[str, str]]


def build_x31_xml(
    entries: list[tuple[str, Decimal]],
    *,
    boq_name: str,
    project_name: str,
    service_start: date | None = None,
    service_end: date | None = None,
    today: date | None = None,
) -> X31Export:
    """Build a schema-valid X31 from ``(ordinal, quantity)`` pairs in bill order.

    Element order follows ``tgGAEBQD`` / ``tgQtyDetermination``: ``GAEBInfo``,
    then ``QtyDeterm`` holding ``PrjInfo``, ``QtyDetermInfo``, ``DP``,
    ``BoQ``. ``DP`` comes after ``QtyDetermInfo`` in this phase, unlike the
    80 phases. ``BoQBkdn`` sits directly in ``BoQ`` (there is no ``BoQInfo``).

    An ordinal the GAEB OZ grammar cannot carry, one of a depth the rest of
    the bill does not share, a duplicate, or a quantity beyond the 11.3
    decimal type is not written. Each is returned in ``skipped`` with a
    reason, so the caller can tell the person instead of handing over a file
    that silently lacks lines.
    """
    skipped: list[dict[str, str]] = []
    valid: list[tuple[str, Decimal]] = []
    for ordinal, quantity in entries:
        qty = q3(quantity)
        if abs(qty) >= _QTY_LIMIT:
            skipped.append({"ordinal": ordinal, "reason": "quantity_out_of_range"})
            continue
        valid.append((ordinal, qty))

    layout = plan_oz_layout(o for o, _ in valid)
    skipped.extend(layout.rejected)

    root = ET.Element("GAEB", xmlns=namespace_for("31"))
    append_gaeb_info(root, today)
    qd = ET.SubElement(root, "QtyDeterm")
    prj = ET.SubElement(qd, "PrjInfo")
    ET.SubElement(prj, "RefPrjName").text = (project_name or "")[:60]
    info = ET.SubElement(qd, "QtyDetermInfo")
    ET.SubElement(info, "MethodDescription").text = METHOD_REB_2009
    if service_start is not None:
        ET.SubElement(info, "ServiceProvisionStartDate").text = service_start.isoformat()
    if service_end is not None:
        ET.SubElement(info, "ServiceProvisionEndDate").text = service_end.isoformat()
    ET.SubElement(qd, "DP").text = "31"
    boq = ET.SubElement(qd, "BoQ", ID=mint_id("oeBoQ"))
    ET.SubElement(boq, "RefBoQName").text = (boq_name or "")[:20]
    if layout.depth:
        append_bkdn(boq, layout)
    else:
        # BoQBkdn is required (minOccurs=1) even for an empty measurement.
        bkdn = ET.SubElement(boq, "BoQBkdn")
        ET.SubElement(bkdn, "Type").text = "Item"
        ET.SubElement(bkdn, "Length").text = "4"
        ET.SubElement(bkdn, "Num").text = "Yes"
    body = ET.SubElement(boq, "BoQBody")

    written: list[str] = []

    def _emit(itemlist: ET.Element, leaf: str, ordinal: str, qty: Decimal) -> None:
        item = ET.SubElement(itemlist, "Item", ID=mint_id("oeItem"), RNoPart=leaf)
        determ = ET.SubElement(item, "QtyDeterm")
        ET.SubElement(determ, "Qty").text = str(qty)
        written.append(ordinal)

    write_oz_body(body, layout, valid, emit_item=_emit)
    return X31Export(xml=serialize(root), written=written, skipped=skipped)


# ── Import ───────────────────────────────────────────────────────────────


@dataclass(slots=True)
class X31Item:
    """One measured item read from a file."""

    oz: str
    quantity: Decimal | None
    rows: list[str] = field(default_factory=list)


@dataclass(slots=True)
class ParsedX31:
    """What an X31 file says, before it is held against any bill."""

    items: list[X31Item]
    method: str = ""
    project_name: str = ""
    boq_name: str = ""
    service_start: str = ""
    service_end: str = ""
    warnings: list[dict[str, str]] = field(default_factory=list)


def parse_x31(content: bytes) -> ParsedX31:
    """Read an X31 upload. Raises :class:`ImporterParseError` for anything else.

    Another GAEB phase is refused by name rather than read as a measurement:
    an X83 also has a ``Qty`` per item, and taking a tender's quantities for
    a site measurement is exactly the confusion this check exists to stop.
    """
    root = parse_xml(content, label="GAEB X31")
    if _local(root.tag) != "GAEB":
        raise ImporterParseError("Not a GAEB DA XML document (root element is not <GAEB>).")
    phase = exchange_phase(root)
    if phase and phase != "31":
        raise ImporterParseError(
            f"This is a GAEB X{phase} file, not an X31 quantity determination. "
            "Import tender phases (X81 to X86) through the normal BOQ import."
        )
    container = _find_child(root, "QtyDeterm")
    if container is None:
        raise ImporterParseError("No <QtyDeterm> element found. Is this a GAEB X31 file?")
    boq = _find_child(container, "BoQ")
    if boq is None:
        raise ImporterParseError("The X31 file has no <BoQ>, so it names no positions.")

    info = _find_child(container, "QtyDetermInfo")
    prj = _find_child(container, "PrjInfo")
    parsed = ParsedX31(
        items=[],
        method=_text_of(info, "MethodDescription") if info is not None else "",
        project_name=_text_of(prj, "RefPrjName") if prj is not None else "",
        boq_name=_text_of(boq, "RefBoQName"),
        service_start=_text_of(info, "ServiceProvisionStartDate") if info is not None else "",
        service_end=_text_of(info, "ServiceProvisionEndDate") if info is not None else "",
    )

    for file_item in iter_boq_items(boq):
        determ = _find_child(file_item.element, "QtyDeterm")
        quantity: Decimal | None = None
        rows: list[str] = []
        if determ is not None:
            raw_qty = _text_of(determ, "Qty")
            quantity = dec(raw_qty.replace(",", ".")) if raw_qty else None
            if raw_qty and quantity is None:
                parsed.warnings.append({"ordinal": file_item.oz, "warning": "unreadable_quantity"})
            for determ_item in determ:
                if _local(determ_item.tag) != "QDetermItem":
                    continue
                takeoff = _find_child(determ_item, "QTakeoff")
                if takeoff is not None:
                    rows.append((takeoff.get("Row") or "").rstrip())
        parsed.items.append(X31Item(oz=file_item.oz, quantity=quantity, rows=rows))
    return parsed


def measured_quantity_of(position: Any) -> Decimal | None:
    """The total of a position's stored measurement sheet, or ``None``.

    Built through the measurement library with ``strict=False``, exactly as
    the measurement endpoints read a stored sheet, so a line with a bad
    formula counts as zero here as it does on screen.
    """
    from app.modules.measurement import build_sheet
    from app.modules.measurement.formula import MeasurementError

    meta = getattr(position, "metadata_", None)
    if not isinstance(meta, dict):
        meta = getattr(position, "metadata", None)
    if not isinstance(meta, dict):
        return None
    stored = meta.get("measurement")
    if not isinstance(stored, dict):
        return None
    lines = [ln for ln in (stored.get("lines") or []) if isinstance(ln, dict)]
    if not lines:
        return None
    try:
        sheet = build_sheet(
            item_ref=str(getattr(position, "ordinal", "") or ""),
            description="",
            unit=str(stored.get("unit") or getattr(position, "unit", "") or ""),
            lines=lines,
            strict=False,
        )
    except MeasurementError:
        return None
    return sheet.total_quantity


def propose_x31(parsed: ParsedX31, positions: list[Any], *, is_section: Any) -> dict[str, Any]:
    """Hold a parsed X31 against a bill and propose, never apply.

    Returns ``matched`` (one proposal per position, with the quantity it
    carries now, its current measured total and the measured quantity from
    the file), ``unmatched`` (every OZ that found no single position, with
    the reason) and counts. An OZ that occurs twice in the file is not
    proposed at all: which of two totals is the measurement is a question
    for the person who sent it.
    """
    index = PositionIndex(positions, is_section=is_section)
    oz_counts: dict[str, int] = {}
    for item in parsed.items:
        oz_counts[item.oz] = oz_counts.get(item.oz, 0) + 1

    matched: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    claimed: dict[str, str] = {}
    for item in parsed.items:
        base = {
            "oz": item.oz,
            "quantity": str(item.quantity) if item.quantity is not None else None,
            "row_count": len(item.rows),
            "rows": item.rows[:MAX_ROWS_PER_ITEM],
        }
        if oz_counts[item.oz] > 1:
            unmatched.append({**base, "reason": "duplicate_oz_in_file"})
            continue
        if item.quantity is None:
            reason = "rows_without_total" if item.rows else "no_quantity"
            unmatched.append({**base, "reason": reason})
            continue
        found = index.match(item.oz)
        if found.status == "ambiguous":
            unmatched.append(
                {
                    **base,
                    "reason": "ambiguous_oz",
                    "candidates": [str(getattr(p, "ordinal", "") or "") for p in found.candidates],
                }
            )
            continue
        if found.status != "matched":
            unmatched.append({**base, "reason": "unknown_oz"})
            continue
        pos = found.position
        pos_id = str(getattr(pos, "id", "") or "")
        if pos_id in claimed:
            # Two different OZ of the file normalised onto one position.
            unmatched.append({**base, "reason": "position_already_matched", "matched_oz": claimed[pos_id]})
            continue
        claimed[pos_id] = item.oz
        current_qty = dec(getattr(pos, "quantity", None)) or Decimal("0")
        current_measured = measured_quantity_of(pos)
        proposed = item.quantity
        matched.append(
            {
                **base,
                "position_id": pos_id,
                "ordinal": str(getattr(pos, "ordinal", "") or ""),
                "description": str(getattr(pos, "description", "") or "")[:300],
                "unit": str(getattr(pos, "unit", "") or ""),
                "matched_via": found.via,
                "current_quantity": str(q3(current_qty)),
                "current_measured_quantity": str(q3(current_measured)) if current_measured is not None else None,
                "proposed_quantity": str(q3(proposed)),
                "difference_to_quantity": str(q3(proposed - current_qty)),
                "unchanged": current_measured is not None and q3(current_measured) == q3(proposed),
            }
        )

    measurable = [p for p in positions if not is_section(p)]
    return {
        "method": parsed.method,
        "project_name": parsed.project_name,
        "boq_name": parsed.boq_name,
        "service_start": parsed.service_start,
        "service_end": parsed.service_end,
        "items_in_file": len(parsed.items),
        "matched": matched,
        "unmatched": unmatched,
        "positions_not_in_file": max(len(measurable) - len(matched), 0),
        "warnings": parsed.warnings,
    }


def measurement_from_x31(
    quantity: Decimal,
    *,
    unit: str,
    file_name: str,
    oz: str,
    rows: list[str],
) -> dict[str, Any]:
    """The ``metadata.measurement`` sheet a confirmed X31 quantity becomes.

    One line whose formula is the measured total, so the existing sheet
    machinery (drawer, ``reconcile``, the REB/OENORM renderings) reads it
    like any hand-entered sheet. The file's own rows travel beside it under
    ``gaeb_x31`` for the audit trail. Deliberately no timestamp: confirming
    the same file twice must leave the same sheet, not two different ones.
    """
    label = f"GAEB X31 {file_name}".strip()[:200]
    return {
        "unit": unit,
        "lines": [
            {
                "description": label,
                "formula": str(q3(quantity)),
                "variables": {},
                "factor": "1",
                "sign": "+",
                "ref": oz,
                "unit": unit,
            }
        ],
        "source": "gaeb_x31",
        "gaeb_x31": {
            "file_name": file_name[:200],
            "oz": oz,
            "quantity": str(q3(quantity)),
            "rows": [str(r)[:80] for r in rows[:MAX_ROWS_PER_ITEM]],
            "row_count": len(rows),
        },
    }


__all__ = [
    "MAX_ROWS_PER_ITEM",
    "METHOD_REB_2009",
    "ParsedX31",
    "X31Export",
    "X31Item",
    "build_x31_xml",
    "measured_quantity_of",
    "measurement_from_x31",
    "parse_x31",
    "propose_x31",
]
