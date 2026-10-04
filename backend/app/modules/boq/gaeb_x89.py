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
* VAT is computed once, on that net total, and ``TotalGross`` is net plus
  VAT exactly. The bill's own tax treatment decides the rate, the way the
  X84 export reads tax from the bill's tax markups (see the router).
* Retention is a ``security deposit`` share marked as a counter claim. It is
  taken off what is payable, not off the taxable amount: VAT is owed on the
  whole performance.

Check
-----
:func:`check_x89` reads an invoice someone sent and holds it against the
bill, position by position. Nothing is written. Per OZ it reports an
unknown OZ, a unit price that differs from the bill's rate, a line whose
``BillQty x UP`` does not make its ``IT``, and a billed quantity above the
bill quantity; then it reconciles the totals. The per-line differences add
up to the total difference by construction, which a test pins.
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
from app.modules.boq.units import to_gaeb_unit_code

#: ``tgInvoiceType`` values this module writes.
INVOICE_TYPE_PROGRESS = "deduction"
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


@dataclass(slots=True)
class InvoiceFigures:
    """The totals an X89 states, all at two decimals."""

    net: Decimal
    vat_rate: Decimal
    vat_amount: Decimal
    gross: Decimal
    retention: Decimal
    payable: Decimal

    def as_strings(self) -> dict[str, str]:
        return {
            "net": str(self.net),
            "vat_rate": str(self.vat_rate),
            "vat_amount": str(self.vat_amount),
            "gross": str(self.gross),
            "retention": str(self.retention),
            "payable": str(self.payable),
        }


def invoice_figures(lines: list[InvoiceLine], *, vat_rate: Decimal, retention: Decimal) -> InvoiceFigures:
    """Net from the cent-rounded line amounts, VAT once on the net, gross exactly."""
    net = sum((c2(ln.amount) for ln in lines), _ZERO)
    rate = c2(vat_rate)
    vat_amount = c2(net * rate / _HUNDRED)
    gross = net + vat_amount
    held = c2(retention)
    return InvoiceFigures(
        net=net,
        vat_rate=rate,
        vat_amount=vat_amount,
        gross=gross,
        retention=held,
        payable=gross - held,
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


def build_x89_xml(data: InvoiceInput, *, today: date | None = None) -> X89Export:
    """Write ``data`` as a schema-valid X89. Call :func:`missing_invoice_fields` first.

    Element order follows ``tgGAEB`` (``GAEBInfo``, ``PrjInfo``, ``Invoice``)
    and ``tgInvoice`` (``DP``, ``BoQ``, ``InvoiceHeader``, ``InvoiceCreator``,
    ``InvoiceRecipient``, ``InvoiceShare``+, ``TotalGross``). The bill is
    written with every claimed line under its OZ. A line whose OZ GAEB cannot
    spell is not dropped, because its money is part of the claim: it goes
    under a ``ZZ`` category with a running number and the original reference
    in its text, and the caller is told.
    """
    missing = missing_invoice_fields(data)
    if missing:
        raise ValueError(f"X89 is missing mandatory fields: {', '.join(missing)}")
    assert data.invoice_date is not None and data.period_start is not None and data.period_end is not None

    figures = invoice_figures(data.lines, vat_rate=data.vat_rate, retention=data.retention)

    # Place every line: its own OZ where GAEB can spell it, a fallback OZ
    # otherwise. The fallback keeps the depth the rest of the bill has.
    layout = plan_oz_layout(ln.oz for ln in data.lines)
    depth = layout.depth or 1
    remapped: list[dict[str, str]] = []
    placed: list[tuple[str, InvoiceLine]] = []
    fallback_no = 0
    for ln in data.lines:
        if ln.oz.strip() in layout.accepted and ln.oz.strip() not in {o for o, _ in placed}:
            placed.append((ln.oz.strip(), ln))
            continue
        fallback_no += 1
        synthetic = ".".join([FALLBACK_CATEGORY] * (depth - 1) + [f"Z{fallback_no:03d}"])
        reason = next((r["reason"] for r in layout.rejected if r["ordinal"] == ln.oz.strip()), "duplicate_ordinal")
        remapped.append({"ordinal": ln.oz, "written_as": synthetic, "reason": reason})
        placed.append((synthetic, ln))
    final_layout = plan_oz_layout(o for o, _ in placed)
    # Every placed OZ shares one depth by construction, so nothing is rejected.

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
    ET.SubElement(totals, "VAT").text = str(figures.vat_rate)
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
    # tax on it, and what is held back from payment. The last share states
    # what is left to pay, so a reader does not have to redo the arithmetic.
    _share(invoice, "basic amount", "Leistung des Abrechnungszeitraums, netto", figures.net)
    _share(invoice, "VAT", f"Umsatzsteuer {_fmt_pct(figures.vat_rate)} %", figures.vat_amount)
    if figures.retention:
        _share(invoice, "security deposit", "Sicherheitseinbehalt", figures.retention, counter=True)
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
        for file_item in iter_boq_items(boq):
            el = file_item.element
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


def check_x89(parsed: ParsedX89, positions: list[Any], *, is_section: Any) -> dict[str, Any]:
    """Hold an invoice against the bill. Reports differences; applies nothing.

    For each invoiced item the *expected* amount is ``BillQty`` times the
    bill's unit rate for that position, to the cent. The item's difference
    is what the invoice claims minus that. An item whose OZ names no single
    position has no expectation, so its whole amount is its difference. That
    makes the per-item differences add up to the invoice net minus the
    expected net exactly, which is the property a checker relies on when it
    reads the total first and drills down second.
    """
    index = PositionIndex(positions, is_section=is_section)
    lines: list[dict[str, Any]] = []
    invoiced_total = _ZERO
    expected_total = _ZERO
    issue_counts: dict[str, int] = {}

    for item in parsed.items:
        amount = c2(item.amount) if item.amount is not None else _ZERO
        invoiced_total += amount
        issues: list[str] = []
        entry: dict[str, Any] = {
            "oz": item.oz,
            "description": item.description,
            "unit": item.unit,
            "bill_qty": str(q3(item.bill_qty)) if item.bill_qty is not None else None,
            "unit_price": str(q3(item.unit_price)) if item.unit_price is not None else None,
            "amount": str(amount),
        }
        if item.amount is None:
            issues.append("missing_amount")
        if item.bill_qty is not None and item.unit_price is not None and item.amount is not None:
            arithmetic = c2(item.bill_qty * item.unit_price)
            if arithmetic != amount:
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
            expected = c2(qty * rate)
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
            if item.bill_qty is not None and boq_qty > 0 and item.bill_qty > boq_qty:
                issues.append("quantity_above_boq")
        entry["issues"] = issues
        for issue in issues:
            issue_counts[issue] = issue_counts.get(issue, 0) + 1
        lines.append(entry)

    totals_check: list[dict[str, Any]] = []

    def _compare(key: str, stated: str | None, computed: Decimal) -> None:
        stated_dec = dec(stated) if stated else None
        totals_check.append(
            {
                "key": key,
                "stated": str(stated_dec) if stated_dec is not None else None,
                "computed": str(computed),
                "matches": stated_dec is not None and c2(stated_dec) == computed,
            }
        )

    _compare("items_total", parsed.totals.get("Total"), invoiced_total)
    vat_rate = dec(parsed.totals.get("VAT")) if parsed.totals.get("VAT") else None
    net_stated = dec(parsed.totals.get("TotalNet")) if parsed.totals.get("TotalNet") else None
    if vat_rate is not None:
        base = net_stated if net_stated is not None else invoiced_total
        _compare("vat_amount", parsed.totals.get("VATAmount"), c2(base * vat_rate / _HUNDRED))
    vat_stated = dec(parsed.totals.get("VATAmount")) if parsed.totals.get("VATAmount") else None
    if net_stated is not None and vat_stated is not None:
        _compare("total_gross", parsed.totals.get("TotalGross"), c2(net_stated + vat_stated))
    if parsed.total_gross and parsed.totals.get("TotalGross"):
        _compare("invoice_total_gross", parsed.total_gross, c2(dec(parsed.totals["TotalGross"]) or _ZERO))

    measurable = [p for p in positions if not is_section(p)]
    return {
        "header": parsed.header,
        "currency": parsed.currency,
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
    "FALLBACK_CATEGORY",
    "INVOICE_TYPES",
    "INVOICE_TYPE_PROGRESS",
    "InvoiceFigures",
    "InvoiceInput",
    "InvoiceLine",
    "InvoiceParty",
    "ParsedX89",
    "X89Export",
    "X89Item",
    "build_x89_xml",
    "check_x89",
    "invoice_figures",
    "invoice_lines_from_claim",
    "missing_invoice_fields",
    "parse_x89",
]
