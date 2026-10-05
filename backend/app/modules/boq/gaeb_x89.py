# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""GAEB DA XML 3.3 X89, Rechnung (invoice).

An X89 is a contractor's invoice against the bill: an ``Invoice`` with a
header (number, date, kind, settlement period), the issuer and the
recipient, the invoice shares that build the amount (basic amount, VAT,
security deposit and so on), the gross total, and optionally the bill with
the quantity billed per OZ (Fachdokumentation 3.3, chapter 8).

Export
------
:func:`build_x89_xml` writes one progress claim as an X89. The claim is a
period claim (``SettlementType`` ``periodic``): every line carries this
period's quantity and value, never the cumulative figure, so a second claim
does not bill the first claim's work again. ``InvoiceType`` is
``deduction``, the schema's English for an Abschlagsrechnung.

Money rules, each one pinned by a test:

* An item's ``IT`` is the claim line's period value as stored, rounded to
  the cent. It is not recomputed from quantity times rate: a QS may have
  overridden the value, and the invoice has to say what was claimed.
* ``Totals/Total`` and ``TotalNet`` are the sum of the ``IT`` actually
  written, so a receiver adding up the items lands on the total.
* VAT is computed once, on that net total, at the rate as it stands (a
  combined 14.975 % is not rounded to 14.98 first), and ``TotalGross`` is
  net plus VAT exactly. The bill's own tax treatment decides the rate, the
  way the X84 export reads tax from the bill's tax markups (see the router).
* Retention is a ``security deposit`` share marked as a counter claim. It is
  taken off what is payable, not off the taxable amount: VAT is owed on the
  whole performance. Only retention on the work this invoice bills is taken
  off; the caller leaves out retention on stored materials, which an X89
  does not bill.
* Retention released and billed on the claim is paid with it. It is its own
  share, not taxable and not a counter claim, and it is added to what is
  payable, so the outstanding amount before VAT is what the claim says is
  due.

Check
-----
:func:`check_x89` reads an invoice someone sent and holds it against the
bill, position by position. Nothing is written. Per OZ it reports an
unknown OZ, a unit price that differs from the bill's rate, a line whose
``BillQty x UP`` does not make its ``IT``, and a billed quantity above the
bill quantity; a ``MarkupItem`` (discount or surcharge) is held against the
bill's markup of the same percentage. Then it reconciles the totals. The
per-line differences add up to the total difference by construction, which
a test pins.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from app.modules.boq.gaeb_common import (
    OzLayout,
    PositionIndex,
    append_bkdn,
    append_gaeb_info,
    c2,
    dec,
    exchange_phase,
    iter_boq_items,
    mint_id,
    ml_text,
    namespace_for,
    parse_xml,
    plan_oz_layout,
    q3,
    serialize,
    write_oz_body,
)
from app.modules.boq.importers._base import ImporterParseError
from app.modules.boq.importers.gaeb_xml import _find_child, _local, _text_of
from app.modules.boq.markup_base import has_base, resolve_markup_base
from app.modules.boq.units import to_gaeb_unit_code

#: ``tgInvoiceType`` values this module writes. Only ``deduction`` (an
#: Abschlagsrechnung) and ``single invoice`` are built correctly from one
#: period's claim; a final account has to bill the cumulative figure less
#: the earlier payments, which is not built yet (see the router).
INVOICE_TYPE_PROGRESS = "deduction"
CUMULATIVE_INVOICE_TYPES = ("final account", "part final account")
INVOICE_TYPES = (
    "deduction",
    "final account",
    "part final account",
    "advance payment",
    "single invoice",
    "pro forma invoice",
    "reviewed invoice",
)

#: Where a line whose OZ GAEB cannot spell goes, so no claimed money is lost.
FALLBACK_CATEGORY = "ZZ"

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")
_C1 = Decimal("0.01")


@dataclass(slots=True)
class InvoiceParty:
    """Issuer or recipient of an invoice, as far as the platform knows it."""

    name: str = ""
    street: str = ""
    postcode: str = ""
    city: str = ""
    country: str = ""
    tax_no: str = ""
    vat_id: str = ""


@dataclass(slots=True)
class InvoiceLine:
    """One claim line, ready to be written as an X89 ``Item``.

    ``amount`` is the period value as claimed. ``bill_qty`` and
    ``unit_price`` say how it was arrived at; for a line billed by percent
    of a lump sum, ``bill_qty`` is the fraction and ``unit_price`` the lump.
    """

    oz: str
    description: str
    unit: str
    bill_qty: Decimal
    unit_price: Decimal | None
    amount: Decimal
    #: The ``RNoIndex`` a GAEB import recorded for the linked position, if any.
    index: str = ""


@dataclass(slots=True)
class InvoiceInput:
    """Everything an X89 needs, gathered from a claim by the caller."""

    invoice_no: str
    invoice_date: date | None
    period_start: date | None
    period_end: date | None
    currency: str
    project_name: str
    boq_name: str
    lines: list[InvoiceLine]
    vat_rate: Decimal
    retention: Decimal
    creator: InvoiceParty
    recipient: InvoiceParty
    invoice_type: str = INVOICE_TYPE_PROGRESS
    sequential_no: int | None = None
    #: Retention released and billed on this claim, paid with it.
    release: Decimal = Decimal("0")


@dataclass(slots=True)
class InvoiceFigures:
    """The totals an X89 states. Money at two decimals, the VAT rate as it stands."""

    net: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    gross: Decimal
    retention: Decimal
    payable: Decimal
    release: Decimal = Decimal("0")

    @property
    def outstanding_before_vat(self) -> Decimal:
        """What is paid for the work, before VAT: net less retention plus released retention."""
        return self.net - self.retention + self.release

    def as_strings(self) -> dict[str, str]:
        return {
            "net": str(self.net),
            "vat_rate": _fmt_rate(self.vat_rate),
            "vat_amount": str(self.vat_amount),
            "gross": str(self.gross),
            "retention": str(self.retention),
            "release": str(self.release),
            "payable": str(self.payable),
            "outstanding_before_vat": str(self.outstanding_before_vat),
        }


def invoice_figures(
    lines: list[InvoiceLine],
    *,
    vat_rate: Decimal,
    retention: Decimal,
    release: Decimal = _ZERO,
) -> InvoiceFigures:
    """Net from the cent-rounded line amounts, VAT once on the net, gross exactly.

    The VAT amount is worked out from the rate as given. Rounding the rate to
    two decimals first made a combined 14.975 % into 14.98 % and put 50.00
    too much VAT on a million of net. ``payable`` is the gross less the
    retention plus the release billed here.
    """
    net = sum((c2(ln.amount) for ln in lines), _ZERO)
    rate = vat_rate.normalize() if vat_rate else _ZERO
    vat_amount = c2(net * rate / _HUNDRED)
    gross = net + vat_amount
    held = c2(retention)
    released = c2(release)
    return InvoiceFigures(
        net=net,
        vat_rate=rate,
        vat_amount=vat_amount,
        gross=gross,
        retention=held,
        payable=gross - held + released,
        release=released,
    )


def missing_invoice_fields(data: InvoiceInput) -> list[str]:
    """Name every mandatory X89 field the platform has no value for.

    The schema requires them and an invoice needs them by law; the export
    refuses rather than writing a placeholder, because a dash in the
    issuer's street is a defect on a document that is meant to be paid.
    """
    missing: list[str] = []
    if not data.invoice_no.strip():
        missing.append("invoice_no")
    if data.invoice_date is None:
        missing.append("invoice_date")
    if data.period_start is None:
        missing.append("period_start")
    if data.period_end is None:
        missing.append("period_end")
    for role, party in (("creator", data.creator), ("recipient", data.recipient)):
        for attr, key in (("name", "name"), ("street", "street"), ("postcode", "postcode"), ("city", "city")):
            if not str(getattr(party, attr) or "").strip():
                missing.append(f"{role}.{key}")
    if not (data.creator.tax_no.strip() or data.creator.vat_id.strip()):
        missing.append("creator.tax_no")
    if not data.lines:
        missing.append("lines")
    return missing


def invoice_lines_from_claim(
    claim_lines: list[Any],
    contract_lines: dict[Any, Any],
    linked_positions: dict[Any, Any],
    *,
    position_for_line: Any,
) -> tuple[list[InvoiceLine], dict[Any, int]]:
    """Turn a claim's lines into X89 lines, in schedule order. Pure.

    Each line bills THIS PERIOD: ``period_completed_qty`` and
    ``period_completed_value``. The cumulative columns are what the earlier
    claims already invoiced plus this one; writing them would bill the
    earlier periods a second time on every invoice.

    The OZ is the linked bill position's ordinal when the schedule line is
    linked to a position of this project, otherwise the schedule line's own
    code. A line with neither a quantity nor a value this period is not
    billed and not written.

    Returns the lines and, per bill, how many lines are linked into it, so
    the caller can tell which bill the invoice is against.
    """
    boq_counts: dict[Any, int] = {}
    keyed: list[tuple[tuple[int, str], InvoiceLine]] = []
    for cl in claim_lines:
        sov = contract_lines.get(cl.contract_line_id)
        if sov is None:
            continue
        value = dec(cl.period_completed_value) or Decimal("0")
        qty = dec(cl.period_completed_qty) or Decimal("0")
        pct = dec(cl.period_completed_pct) or Decimal("0")
        if value == 0 and qty == 0:
            continue
        pos_id = position_for_line(sov)
        pos = linked_positions.get(pos_id) if pos_id else None
        if pos is not None:
            boq_counts[pos.boq_id] = boq_counts.get(pos.boq_id, 0) + 1
        oz = str((pos.ordinal if pos is not None else sov.code) or "").strip()
        description = str((pos.description if pos is not None else sov.description) or sov.description or "")
        unit_token = str((pos.unit if pos is not None else sov.unit) or sov.unit or "")
        bill_qty: Decimal
        unit_price: Decimal | None
        if qty != 0:
            bill_qty = qty
            unit_price = dec(sov.unit_rate)
            unit = to_gaeb_unit_code(unit_token)
        else:
            # Billed by value: a share of the line as a lump sum. The fraction
            # is the quantity, the line value the price, the claimed value the
            # amount, which stays authoritative whatever the fraction rounds to.
            line_value = dec(sov.total_value) or Decimal("0")
            if pct != 0 and line_value != 0:
                bill_qty = pct / Decimal("100")
                unit_price = line_value
            else:
                bill_qty = Decimal("1")
                unit_price = value
            unit = "psch"
        index = ""
        if pos is not None:
            meta = getattr(pos, "metadata_", None)
            if isinstance(meta, dict):
                index = str(meta.get("gaeb_rno_index") or "").strip()
        keyed.append(
            (
                (int(getattr(sov, "order_index", 0) or 0), str(sov.code or "")),
                InvoiceLine(
                    oz=oz,
                    description=description.strip()[:500],
                    unit=unit[:4],
                    bill_qty=bill_qty,
                    unit_price=unit_price,
                    amount=value,
                    index=index,
                ),
            )
        )
    keyed.sort(key=lambda pair: pair[0])
    return [ln for _, ln in keyed], boq_counts


@dataclass(slots=True)
class X89Export:
    """A written X89 with its figures and the lines that had to be renumbered."""

    xml: str
    figures: InvoiceFigures
    remapped: list[dict[str, str]] = field(default_factory=list)


@dataclass(slots=True)
class InvoicePlacement:
    """Where every invoice line goes in the X89's bill, worked out before anything is written.

    ``placed`` is ``(written OZ, line)`` in bill order, ``layout`` the tree they
    are written as, ``merged`` the OZ whose lines were added into one item, and
    ``remapped`` every line that could not keep its own OZ, with the OZ it is
    written under and why. The preview reports ``remapped`` so a person sees it
    before downloading, and the figures are taken from ``placed``, so the total
    is the sum of the items the file really has.
    """

    placed: list[tuple[str, InvoiceLine]]
    layout: OzLayout
    merged: list[str]
    remapped: list[dict[str, str]]


def _mergeable(a: InvoiceLine, b: InvoiceLine) -> bool:
    if a.unit != b.unit or a.index != b.index:
        return False
    if a.unit_price is None or b.unit_price is None:
        return a.unit_price is None and b.unit_price is None
    return q3(a.unit_price) == q3(b.unit_price)


def place_invoice_lines(lines: list[InvoiceLine]) -> InvoicePlacement:
    """Give every claim line an OZ in the X89. Pure.

    Two schedule lines linked to one bill position name the same OZ. When
    they bill it in the same unit at the same price they are one item of the
    invoice: the quantities and the cent-rounded amounts are added. Otherwise
    the first keeps the OZ. An Indexposition keeps its OZ as base plus
    ``RNoIndex``. A line whose OZ GAEB still cannot spell is not dropped,
    because its money is part of the claim: it goes under a ``ZZ`` category
    with a running number and the original reference in its text, and is
    listed in ``remapped``.
    """
    merged_by_oz: dict[str, InvoiceLine] = {}
    order: list[InvoiceLine] = []
    merged: list[str] = []
    for ln in lines:
        key = ln.oz.strip()
        first = merged_by_oz.get(key) if key else None
        if first is not None and _mergeable(first, ln):
            first.bill_qty = first.bill_qty + ln.bill_qty
            first.amount = c2(first.amount) + c2(ln.amount)
            if key not in merged:
                merged.append(key)
            continue
        copy = InvoiceLine(
            oz=ln.oz,
            description=ln.description,
            unit=ln.unit,
            bill_qty=ln.bill_qty,
            unit_price=ln.unit_price,
            amount=ln.amount,
            index=ln.index,
        )
        if key and first is None:
            merged_by_oz[key] = copy
        order.append(copy)

    index_of = {ln.oz.strip(): ln.index for ln in order if ln.index}
    # A second line under an OZ it could not be merged into is a duplicate
    # for the layout too; only the first one is offered under that OZ.
    offered: list[str] = []
    taken: set[str] = set()
    for ln in order:
        key = ln.oz.strip()
        if key and key not in taken:
            taken.add(key)
            offered.append(key)
    layout = plan_oz_layout(offered, index_of=index_of)
    depth = layout.depth or 1
    remapped: list[dict[str, str]] = []
    placed: list[tuple[str, InvoiceLine]] = []
    used: set[str] = set()
    fallback_no = 0
    for ln in order:
        key = ln.oz.strip()
        if key in layout.accepted and key not in used:
            used.add(key)
            placed.append((key, ln))
            continue
        fallback_no += 1
        synthetic = ".".join([FALLBACK_CATEGORY] * (depth - 1) + [f"Z{fallback_no:03d}"])
        reason = next(
            (r["reason"] for r in layout.rejected if r["ordinal"] == key),
            "duplicate_ordinal" if key else "empty_ordinal",
        )
        remapped.append({"ordinal": ln.oz, "written_as": synthetic, "reason": reason})
        placed.append((synthetic, ln))
    # Every placed OZ shares one depth by construction, so nothing is rejected.
    final_layout = plan_oz_layout((o for o, _ in placed), index_of=layout.index)
    return InvoicePlacement(placed=placed, layout=final_layout, merged=merged, remapped=remapped)


def x89_figures(data: InvoiceInput) -> tuple[InvoiceFigures, InvoicePlacement]:
    """The figures and the placement the X89 of ``data`` will carry. Preview and export both read this."""
    placement = place_invoice_lines(data.lines)
    figures = invoice_figures(
        [ln for _, ln in placement.placed],
        vat_rate=data.vat_rate,
        retention=data.retention,
        release=data.release,
    )
    return figures, placement


def _address(parent: ET.Element, party: InvoiceParty) -> None:
    addr = ET.SubElement(parent, "Address")
    ET.SubElement(addr, "Name1").text = party.name[:40]
    ET.SubElement(addr, "Street").text = party.street[:40]
    ET.SubElement(addr, "PCode").text = party.postcode[:20]
    ET.SubElement(addr, "City").text = party.city[:40]
    if party.country.strip():
        ET.SubElement(addr, "Country").text = party.country[:40]
    if party.vat_id.strip():
        ET.SubElement(addr, "VATID").text = party.vat_id[:80]


def _share(parent: ET.Element, share_type: str, description: str, total: Decimal, *, counter: bool = False) -> None:
    share = ET.SubElement(parent, "InvoiceShare")
    ET.SubElement(share, "InvoiceShareType").text = share_type
    ET.SubElement(share, "Description").text = description[:256]
    ET.SubElement(share, "Total").text = str(c2(total))
    if counter:
        ET.SubElement(share, "CounterClaim").text = "Yes"


def _fmt_pct(rate: Decimal) -> str:
    text = format(rate.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _fmt_rate(rate: Decimal) -> str:
    """A VAT rate for ``Totals/VAT``: two decimals, or more when the rate has them (14.975)."""
    exponent = rate.normalize().as_tuple().exponent
    if isinstance(exponent, int) and exponent < -2:
        return format(rate.normalize(), "f")
    return str(c2(rate))


def build_x89_xml(data: InvoiceInput, *, today: date | None = None) -> X89Export:
    """Write ``data`` as a schema-valid X89. Call :func:`missing_invoice_fields` first.

    Element order follows ``tgGAEB`` (``GAEBInfo``, ``PrjInfo``, ``Invoice``)
    and ``tgInvoice`` (``DP``, ``BoQ``, ``InvoiceHeader``, ``InvoiceCreator``,
    ``InvoiceRecipient``, ``InvoiceShare``+, ``TotalGross``). The bill is
    written with every claimed line under its OZ, as
    :func:`place_invoice_lines` places it; the lines that could not keep
    their OZ come back in ``remapped``.
    """
    missing = missing_invoice_fields(data)
    if missing:
        raise ValueError(f"X89 is missing mandatory fields: {', '.join(missing)}")
    assert data.invoice_date is not None and data.period_start is not None and data.period_end is not None

    figures, placement = x89_figures(data)
    placed = placement.placed
    final_layout = placement.layout
    remapped = placement.remapped

    root = ET.Element("GAEB", xmlns=namespace_for("89"))
    append_gaeb_info(root, today)
    prj = ET.SubElement(root, "PrjInfo")
    ET.SubElement(prj, "NamePrj").text = (data.project_name or "")[:60]
    if data.currency.strip():
        ET.SubElement(prj, "Cur").text = data.currency.strip()[:3].upper()

    invoice = ET.SubElement(root, "Invoice")
    ET.SubElement(invoice, "DP").text = "89"

    boq = ET.SubElement(invoice, "BoQ", ID=mint_id("oeBoQ"))
    boq_info = ET.SubElement(boq, "BoQInfo")
    ET.SubElement(boq_info, "Name").text = (data.boq_name or data.invoice_no or "")[:20]
    ET.SubElement(boq_info, "LblBoQ").text = (data.project_name or data.boq_name or "")[:60]
    ET.SubElement(boq_info, "OutlCompl").text = "OutTxt"
    append_bkdn(boq_info, final_layout)
    totals = ET.SubElement(boq_info, "Totals")
    ET.SubElement(totals, "Total").text = str(figures.net)
    ET.SubElement(totals, "VAT").text = _fmt_rate(figures.vat_rate)
    ET.SubElement(totals, "TotalNet").text = str(figures.net)
    ET.SubElement(totals, "VATAmount").text = str(figures.vat_amount)
    ET.SubElement(totals, "TotalGross").text = str(figures.gross)

    body = ET.SubElement(boq, "BoQBody")

    def _open(ctgy: ET.Element, path: list[str], _under: list[Any]) -> None:
        label = "Sonstige Positionen" if path and path[0] == FALLBACK_CATEGORY else ".".join(path)
        ml_text(ctgy, "LblTx", label)

    def _close(ctgy: ET.Element, _path: list[str], under: list[Any]) -> None:
        sub = ET.SubElement(ctgy, "Totals")
        ET.SubElement(sub, "Total").text = str(sum((c2(ln.amount) for ln in under), _ZERO))

    def _emit(itemlist: ET.Element, leaf: str, ordinal: str, ln: InvoiceLine) -> None:
        item = ET.SubElement(itemlist, "Item", ID=mint_id("oeItem"), RNoPart=leaf)
        ET.SubElement(item, "BillQty").text = str(q3(ln.bill_qty))
        ET.SubElement(item, "QU").text = (ln.unit or "")[:4]
        if ln.unit_price is not None:
            ET.SubElement(item, "UP").text = str(q3(ln.unit_price))
        ET.SubElement(item, "IT").text = str(c2(ln.amount))
        desc = ET.SubElement(item, "Description")
        outline = ET.SubElement(desc, "OutlineText")
        outl = ET.SubElement(outline, "OutlTxt")
        text = ln.description or ordinal
        if ordinal != ln.oz.strip():
            text = f"{ln.oz} - {text}" if ln.oz.strip() else text
        ml_text(outl, "TextOutlTxt", text[:500])
        # RNoIndex for an Indexposition is set by write_oz_body.

    write_oz_body(body, final_layout, placed, emit_item=_emit, open_category=_open, close_category=_close)

    header = ET.SubElement(invoice, "InvoiceHeader")
    ET.SubElement(header, "InvoiceNo").text = data.invoice_no[:80]
    ET.SubElement(header, "InvoiceDate").text = data.invoice_date.isoformat()
    ET.SubElement(header, "InvoiceType").text = data.invoice_type
    ET.SubElement(header, "SettlementType").text = "periodic"
    if data.sequential_no is not None and data.sequential_no > 0:
        ET.SubElement(header, "SequentialNo").text = str(data.sequential_no)
    ET.SubElement(header, "ServiceProvisionStartDate").text = data.period_start.isoformat()
    ET.SubElement(header, "ServiceProvisionEndDate").text = data.period_end.isoformat()

    creator = ET.SubElement(invoice, "InvoiceCreator")
    _address(creator, data.creator)
    ET.SubElement(creator, "TaxNo").text = (data.creator.tax_no or data.creator.vat_id)[:80]
    recipient = ET.SubElement(invoice, "InvoiceRecipient")
    _address(recipient, data.recipient)
    if data.recipient.tax_no.strip():
        ET.SubElement(recipient, "TaxNo").text = data.recipient.tax_no[:80]

    # The shares in the order the amount is built: what was performed, the
    # tax on it, what is held back from payment and what held-back money is
    # paid out now. The last share states what is left to pay, so a reader
    # does not have to redo the arithmetic.
    _share(invoice, "basic amount", "Leistung des Abrechnungszeitraums, netto", figures.net)
    _share(invoice, "VAT", f"Umsatzsteuer {_fmt_pct(figures.vat_rate)} %", figures.vat_amount)
    if figures.retention:
        _share(invoice, "security deposit", "Sicherheitseinbehalt", figures.retention, counter=True)
    if figures.release:
        # Not a counter claim: released retention is paid, not taken off.
        _share(invoice, "security deposit", "Auszahlung Sicherheitseinbehalt", figures.release)
    if figures.retention or figures.release:
        _share(invoice, "outstanding amount", "Zahlbetrag", figures.payable)
    ET.SubElement(invoice, "TotalGross").text = str(figures.gross)

    return X89Export(xml=serialize(root), figures=figures, remapped=remapped)


# ── Check ────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class X89Item:
    oz: str
    bill_qty: Decimal | None
    unit: str
    unit_price: Decimal | None
    amount: Decimal | None
    description: str
    #: ``"item"`` or ``"markup"`` (a ``MarkupItem``: Zuschlag or Nachlass).
    kind: str = "item"
    #: A markup's percentage (``Markup``) and the base it applies to (``ITMarkup``).
    markup_percent: Decimal | None = None
    markup_base: Decimal | None = None


@dataclass(slots=True)
class ParsedX89:
    items: list[X89Item]
    header: dict[str, str]
    totals: dict[str, str]
    total_gross: str
    shares: list[dict[str, str]]
    currency: str = ""


def _decimal_text(parent: ET.Element | None, name: str) -> Decimal | None:
    if parent is None:
        return None
    raw = _text_of(parent, name)
    return dec(raw.replace(",", ".")) if raw else None


def _outline(item: ET.Element) -> str:
    desc = _find_child(item, "Description")
    if desc is None:
        return ""
    return " ".join("".join(desc.itertext()).split())[:300]


def parse_x89(content: bytes) -> ParsedX89:
    """Read an X89 upload. Raises :class:`ImporterParseError` for anything else."""
    root = parse_xml(content, label="GAEB X89")
    if _local(root.tag) != "GAEB":
        raise ImporterParseError("Not a GAEB DA XML document (root element is not <GAEB>).")
    phase = exchange_phase(root)
    if phase and phase != "89":
        raise ImporterParseError(f"This is a GAEB X{phase} file, not an X89 invoice.")
    invoice = _find_child(root, "Invoice")
    if invoice is None:
        raise ImporterParseError("No <Invoice> element found. Is this a GAEB X89 file?")

    header_el = _find_child(invoice, "InvoiceHeader")
    header = {}
    if header_el is not None:
        for name in (
            "InvoiceNo",
            "InvoiceDate",
            "InvoiceType",
            "SettlementType",
            "SequentialNo",
            "ServiceProvisionStartDate",
            "ServiceProvisionEndDate",
        ):
            value = _text_of(header_el, name)
            if value:
                header[name] = value

    items: list[X89Item] = []
    totals: dict[str, str] = {}
    boq = _find_child(invoice, "BoQ")
    if boq is not None:
        info = _find_child(boq, "BoQInfo")
        totals_el = _find_child(info, "Totals") if info is not None else None
        if totals_el is not None:
            for name in ("Total", "VAT", "TotalNet", "VATAmount", "TotalGross"):
                value = _decimal_text(totals_el, name)
                if value is not None:
                    totals[name] = str(value)
        for file_item in iter_boq_items(boq, include_markup=True):
            el = file_item.element
            if file_item.kind == "markup":
                items.append(
                    X89Item(
                        oz=file_item.oz,
                        bill_qty=None,
                        unit="",
                        unit_price=None,
                        amount=_decimal_text(el, "IT"),
                        description=_outline(el),
                        kind="markup",
                        markup_percent=_decimal_text(el, "Markup"),
                        markup_base=_decimal_text(el, "ITMarkup"),
                    )
                )
                continue
            bill_qty = _decimal_text(el, "BillQty")
            if bill_qty is None:
                bill_qty = _decimal_text(el, "Qty")
            items.append(
                X89Item(
                    oz=file_item.oz,
                    bill_qty=bill_qty,
                    unit=_text_of(el, "QU"),
                    unit_price=_decimal_text(el, "UP"),
                    amount=_decimal_text(el, "IT"),
                    description=_outline(el),
                )
            )

    shares: list[dict[str, str]] = []
    for child in invoice:
        if _local(child.tag) != "InvoiceShare":
            continue
        shares.append(
            {
                "type": _text_of(child, "InvoiceShareType"),
                "description": _text_of(child, "Description"),
                "total": _text_of(child, "Total"),
                "percent": _text_of(child, "Percent"),
                "counter_claim": _text_of(child, "CounterClaim"),
            }
        )
    prj = _find_child(root, "PrjInfo")
    return ParsedX89(
        items=items,
        header=header,
        totals=totals,
        total_gross=_text_of(invoice, "TotalGross"),
        shares=shares,
        currency=_text_of(prj, "Cur") if prj is not None else "",
    )


#: ``BillQty`` has three decimals, so a third of a lump sum arrives cut to
#: 0.333. Half a unit of the third decimal times the price is how far
#: ``BillQty x UP`` can honestly miss ``IT``; half a cent more covers the
#: amount's own rounding. Beyond that the amount really is not the product.
_QTY_HALF_UNIT = Decimal("0.0005")
_HALF_CENT = Decimal("0.005")


def _qty_rounding_tolerance(price: Decimal) -> Decimal:
    return abs(price) * _QTY_HALF_UNIT + _HALF_CENT


def _rate_rounding_tolerance(base: Decimal, rate: Decimal) -> Decimal:
    """How far a VAT amount may sit from ``base x rate`` when the stated rate was cut to two decimals."""
    exponent = rate.as_tuple().exponent
    if isinstance(exponent, int) and exponent <= -2:
        return abs(base) * _HALF_CENT / _HUNDRED + _HALF_CENT
    return _ZERO


def _is_bill_markup(markup: Any) -> bool:
    """A markup of the bill an invoice's ``MarkupItem`` can answer to: active, a percentage, not tax."""
    if not getattr(markup, "is_active", True):
        return False
    if str(getattr(markup, "category", "") or "").lower() == "tax":
        return False
    if str(getattr(markup, "markup_type", "") or "percentage") != "percentage":
        return False
    return dec(getattr(markup, "percentage", None)) is not None


def check_x89(
    parsed: ParsedX89,
    positions: list[Any],
    *,
    is_section: Any,
    markups: list[Any] | tuple[Any, ...] = (),
    bill_currency: str = "",
) -> dict[str, Any]:
    """Hold an invoice against the bill. Reports differences; applies nothing.

    For each invoiced item the *expected* amount is ``BillQty`` times the
    bill's unit rate for that position, to the cent. The item's difference
    is what the invoice claims minus that. An item whose OZ names no single
    position has no expectation, so its whole amount is its difference. That
    makes the per-item differences add up to the invoice net minus the
    expected net exactly, which is the property a checker relies on when it
    reads the total first and drills down second.

    A ``MarkupItem`` (a discount or a surcharge) is a line of its own. Its
    expected amount is the bill's markup of the same percentage applied to
    the expected items, so a -3 % discount the bill also grants differs by
    nothing, and one the bill does not have differs by its whole amount and
    says ``markup_not_in_bill``. ``markups`` are the bill's markups; tax
    markups are VAT and are not held against a ``MarkupItem``.

    ``bill_currency`` is the currency the bill is priced in. An invoice in
    another currency is flagged, because every comparison is then between
    two currencies.
    """
    index = PositionIndex(positions, is_section=is_section)
    lines: list[dict[str, Any]] = []
    invoiced_total = _ZERO
    expected_total = _ZERO
    issue_counts: dict[str, int] = {}
    oz_counts: dict[str, int] = {}
    for item in parsed.items:
        if item.kind == "item":
            oz_counts[item.oz] = oz_counts.get(item.oz, 0) + 1
    # Billed quantity per position across the whole file, so a quantity split
    # over two items under one OZ is held against the bill as one quantity.
    billed_per_position: dict[str, Decimal] = {}
    bill_qty_of: dict[str, Decimal] = {}
    markup_entries: list[tuple[X89Item, dict[str, Any]]] = []

    for item in parsed.items:
        amount = c2(item.amount) if item.amount is not None else _ZERO
        invoiced_total += amount
        issues: list[str] = []
        if item.kind == "markup":
            entry = {
                "oz": item.oz,
                "kind": "markup",
                "description": item.description,
                "unit": "",
                "bill_qty": None,
                "unit_price": None,
                "amount": str(amount),
                "markup_percent": _fmt_pct(item.markup_percent) if item.markup_percent is not None else None,
                "markup_base": str(c2(item.markup_base)) if item.markup_base is not None else None,
                "position_id": None,
                "issues": issues,
            }
            if item.amount is None:
                issues.append("missing_amount")
            if item.markup_base is not None and item.markup_percent is not None and item.amount is not None:
                arithmetic = c2(item.markup_base * item.markup_percent / _HUNDRED)
                if abs(arithmetic - amount) > _C1:
                    issues.append("amount_not_base_times_percent")
                    entry["base_times_percent"] = str(arithmetic)
            lines.append(entry)
            markup_entries.append((item, entry))
            continue
        entry = {
            "oz": item.oz,
            "kind": "item",
            "description": item.description,
            "unit": item.unit,
            "bill_qty": str(q3(item.bill_qty)) if item.bill_qty is not None else None,
            "unit_price": str(q3(item.unit_price)) if item.unit_price is not None else None,
            "amount": str(amount),
        }
        if oz_counts[item.oz] > 1:
            issues.append("duplicate_oz_in_file")
        if item.amount is None:
            issues.append("missing_amount")
        if item.bill_qty is None:
            issues.append("missing_quantity")
        if item.bill_qty is not None and item.unit_price is not None and item.amount is not None:
            product = item.bill_qty * item.unit_price
            arithmetic = c2(product)
            if arithmetic != amount and abs(product - amount) > _qty_rounding_tolerance(item.unit_price):
                issues.append("amount_not_qty_times_price")
                entry["qty_times_price"] = str(arithmetic)

        found = index.match(item.oz)
        if found.status != "matched":
            issues.append("unknown_oz" if found.status == "unmatched" else "ambiguous_oz")
            entry.update({"position_id": None, "expected_amount": None, "difference": str(amount)})
        else:
            pos = found.position
            rate = dec(getattr(pos, "unit_rate", None)) or _ZERO
            boq_qty = dec(getattr(pos, "quantity", None)) or _ZERO
            qty = item.bill_qty if item.bill_qty is not None else _ZERO
            exact = qty * rate
            expected = c2(exact)
            if (
                item.amount is not None
                and expected != amount
                and item.unit_price is not None
                and q3(item.unit_price) == q3(rate)
                and abs(exact - amount) <= _qty_rounding_tolerance(rate)
            ):
                # At the bill's own rate, and off only by the third decimal
                # BillQty was cut to: the amount is what the bill says.
                expected = amount
            expected_total += expected
            entry.update(
                {
                    "position_id": str(getattr(pos, "id", "") or ""),
                    "ordinal": str(getattr(pos, "ordinal", "") or ""),
                    "boq_unit_rate": str(q3(rate)),
                    "boq_quantity": str(q3(boq_qty)),
                    "expected_amount": str(expected),
                    "difference": str(amount - expected),
                }
            )
            if item.unit_price is not None and q3(item.unit_price) != q3(rate):
                issues.append("unit_price_differs")
                entry["unit_price_difference"] = str(q3(item.unit_price) - q3(rate))
            pos_key = entry["position_id"]
            billed_per_position[pos_key] = billed_per_position.get(pos_key, _ZERO) + qty
            bill_qty_of[pos_key] = boq_qty
        entry["issues"] = issues
        lines.append(entry)

    # Markups after every item: their base is the items at bill rates, and a
    # discount category usually comes last in the file anyway.
    items_expected = expected_total
    running = items_expected
    previous_base: Decimal | None = None
    available = [m for m in markups if _is_bill_markup(m)]
    for item, entry in markup_entries:
        amount = c2(item.amount) if item.amount is not None else _ZERO
        pct = item.markup_percent
        match = None
        if pct is not None:
            match = next((m for m in available if q3(dec(m.percentage) or _ZERO) == q3(pct)), None)
        if match is None or pct is None:
            entry["issues"].append("markup_not_in_bill")
            entry.update({"expected_amount": None, "difference": str(amount)})
            continue
        available.remove(match)
        base = resolve_markup_base(
            getattr(match, "apply_to", None),
            direct_cost=items_expected,
            running=running,
            previous_base=previous_base,
        )
        previous_base = base if has_base(getattr(match, "markup_type", None)) else None
        expected = c2(base * pct / _HUNDRED)
        expected_total += expected
        running += expected
        entry.update(
            {
                "bill_markup": str(getattr(match, "name", "") or ""),
                "expected_amount": str(expected),
                "difference": str(amount - expected),
            }
        )

    for entry in lines:
        pos_key = entry.get("position_id")
        if not pos_key:
            continue
        boq_qty = bill_qty_of[pos_key]
        if boq_qty > 0 and billed_per_position[pos_key] > boq_qty:
            entry["issues"].append("quantity_above_boq")
    for entry in lines:
        for issue in entry["issues"]:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1

    totals_check: list[dict[str, Any]] = []

    def _compare(key: str, stated: str | None, computed: Decimal, tolerance: Decimal = _ZERO) -> None:
        stated_dec = dec(stated) if stated else None
        totals_check.append(
            {
                "key": key,
                "stated": str(stated_dec) if stated_dec is not None else None,
                "computed": str(computed),
                "matches": stated_dec is not None and abs(c2(stated_dec) - computed) <= tolerance,
            }
        )

    _compare("items_total", parsed.totals.get("Total"), invoiced_total)
    vat_rate = dec(parsed.totals.get("VAT")) if parsed.totals.get("VAT") else None
    net_stated = dec(parsed.totals.get("TotalNet")) if parsed.totals.get("TotalNet") else None
    if vat_rate is not None:
        base = net_stated if net_stated is not None else invoiced_total
        _compare(
            "vat_amount",
            parsed.totals.get("VATAmount"),
            c2(base * vat_rate / _HUNDRED),
            _rate_rounding_tolerance(base, vat_rate),
        )
    vat_stated = dec(parsed.totals.get("VATAmount")) if parsed.totals.get("VATAmount") else None
    if net_stated is not None and vat_stated is not None:
        _compare("total_gross", parsed.totals.get("TotalGross"), c2(net_stated + vat_stated))
    if parsed.total_gross and parsed.totals.get("TotalGross"):
        _compare("invoice_total_gross", parsed.total_gross, c2(dec(parsed.totals["TotalGross"]) or _ZERO))

    measurable = [p for p in positions if not is_section(p)]
    invoice_currency = (parsed.currency or "").strip().upper()
    bill_cur = (bill_currency or "").strip().upper()
    return {
        "header": parsed.header,
        "currency": parsed.currency,
        "bill_currency": bill_cur,
        "currency_mismatch": bool(invoice_currency and bill_cur and invoice_currency != bill_cur),
        "items_in_file": len(parsed.items),
        "lines": lines,
        "invoiced_total": str(invoiced_total),
        "expected_total": str(expected_total),
        "total_difference": str(invoiced_total - expected_total),
        "issue_counts": issue_counts,
        "totals_check": totals_check,
        "shares": parsed.shares,
        "positions_not_invoiced": max(
            len(measurable) - len({ln["position_id"] for ln in lines if ln.get("position_id")}), 0
        ),
    }


__all__ = [
    "CUMULATIVE_INVOICE_TYPES",
    "FALLBACK_CATEGORY",
    "INVOICE_TYPES",
    "INVOICE_TYPE_PROGRESS",
    "InvoiceFigures",
    "InvoiceInput",
    "InvoiceLine",
    "InvoiceParty",
    "InvoicePlacement",
    "ParsedX89",
    "X89Export",
    "X89Item",
    "build_x89_xml",
    "check_x89",
    "invoice_figures",
    "invoice_lines_from_claim",
    "missing_invoice_fields",
    "parse_x89",
    "place_invoice_lines",
    "x89_figures",
]
