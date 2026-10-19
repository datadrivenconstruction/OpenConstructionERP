# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The FA(3) structure: a writer from neutral inputs and a reader for the rules.

The element order, the choices and the fixed values follow the official schema,
``http://crd.gov.pl/wzor/2025/06/25/13775/schemat.xsd`` (read 2026-10-19), and
the tests validate every document this writes against that file. The field
meanings follow the Ministry of Finance brochure on the FA(3) structure
(https://ksef.podatki.gov.pl/media/nuclnu0w/broszura-informacyjna-dotyczaca-struktury-logicznej-fa-3.pdf).

What it covers: the basic invoice (VAT), the corrective invoice (KOR), the
advance invoice (ZAL), the settlement invoice after advances (ROZ) and the
corrections of the last two. What it leaves out on purpose: new means of
transport, the margin scheme, excise, transport and the attachment block. Those
are written as the "not applicable" choice the schema requires, or not at all
where the element is optional.

The writer computes the per-rate bases and the VAT from the lines, rounding the
VAT once per rate group, which is how the totals P_13_x / P_14_x are defined.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET  # noqa: N817 - writer only; reading goes through defusedxml
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from defusedxml import ElementTree as SafeET

from app.modules.einvoice_ksef.facts import FA3

NS = FA3.namespace
MEDIA_TYPE = "application/xml"

KIND_VAT = "VAT"
KIND_KOR = "KOR"
KIND_ZAL = "ZAL"
KIND_ROZ = "ROZ"
KIND_KOR_ZAL = "KOR_ZAL"
KIND_KOR_ROZ = "KOR_ROZ"
KINDS: tuple[str, ...] = (KIND_VAT, KIND_KOR, KIND_ZAL, KIND_ROZ, KIND_KOR_ZAL, KIND_KOR_ROZ)
CORRECTION_KINDS: frozenset[str] = frozenset({KIND_KOR, KIND_KOR_ZAL, KIND_KOR_ROZ})
ADVANCE_KINDS: frozenset[str] = frozenset({KIND_ZAL, KIND_KOR_ZAL})

# TStawkaPodatku, and the P_13_x / P_14_x pair each rate is summed into. A rate
# with no VAT pair (0%, exempt, outside scope, reverse charge) has ``None``.
RATE_FIELDS: dict[str, tuple[str, str | None]] = {
    "23": ("P_13_1", "P_14_1"),
    "22": ("P_13_1", "P_14_1"),
    "8": ("P_13_2", "P_14_2"),
    "7": ("P_13_2", "P_14_2"),
    "5": ("P_13_3", "P_14_3"),
    "4": ("P_13_4", "P_14_4"),
    "3": ("P_13_4", "P_14_4"),
    "0 KR": ("P_13_6_1", None),
    "0 WDT": ("P_13_6_2", None),
    "0 EX": ("P_13_6_3", None),
    "zw": ("P_13_7", None),
    "np I": ("P_13_8", None),
    "np II": ("P_13_9", None),
    "oo": ("P_13_10", None),
}
VAT_CODES: tuple[str, ...] = tuple(RATE_FIELDS)
# The order the summary fields take in the schema.
_SUMMARY_ORDER: tuple[tuple[str, str | None], ...] = (
    ("P_13_1", "P_14_1"),
    ("P_13_2", "P_14_2"),
    ("P_13_3", "P_14_3"),
    ("P_13_4", "P_14_4"),
    ("P_13_6_1", None),
    ("P_13_6_2", None),
    ("P_13_6_3", None),
    ("P_13_7", None),
    ("P_13_8", None),
    ("P_13_9", None),
    ("P_13_10", None),
)

CENT = Decimal("0.01")


class Fa3BuildError(ValueError):
    """The inputs cannot make a valid FA(3) document. The message says why."""


def rate_percent(vat_code: str) -> Decimal:
    """The VAT percentage a code carries; zero for every code without a VAT amount."""
    return Decimal(vat_code) if vat_code.isdigit() else Decimal("0")


@dataclass(frozen=True)
class Party:
    """Seller or buyer.

    The buyer is identified by exactly one of: a Polish NIP, an EU VAT number
    (``eu_country`` + ``eu_vat``), another tax id (``other_country`` +
    ``other_id``), or nothing (``no_id``, a consumer).
    """

    name: str
    nip: str = ""
    country: str = "PL"
    address_line1: str = ""
    address_line2: str = ""
    eu_country: str = ""
    eu_vat: str = ""
    other_country: str = ""
    other_id: str = ""
    no_id: bool = False
    email: str = ""


@dataclass(frozen=True)
class Line:
    """One invoice line in the invoice currency."""

    description: str
    quantity: Decimal
    unit: str
    unit_net_price: Decimal
    net_amount: Decimal
    vat_code: str
    annex_15: bool = False
    pkwiu: str = ""
    gtu: str = ""
    # P_6A: the delivery date of this line, when lines differ.
    delivery_date: str = ""
    # Correction lines shown "before" (StanPrzed = 1).
    state_before: bool = False


@dataclass(frozen=True)
class CorrectedInvoice:
    """The invoice a correction corrects. ``ksef_number`` empty means issued outside KSeF."""

    number: str
    issue_date: str
    ksef_number: str = ""


@dataclass(frozen=True)
class Correction:
    reason: str
    # TTypKorekty: 1 in the period of the original, 2 in the period of the
    # correction, 3 another date.
    type: int
    corrected: tuple[CorrectedInvoice, ...]


@dataclass(frozen=True)
class AdvanceInvoiceRef:
    """An advance invoice a settlement invoice accounts for."""

    number: str
    ksef_number: str = ""


@dataclass(frozen=True)
class OrderLine:
    """A line of the order or contract an advance invoice is paid against."""

    description: str
    quantity: Decimal
    unit: str
    unit_net_price: Decimal
    net_amount: Decimal
    vat_amount: Decimal
    vat_code: str
    annex_15: bool = False


@dataclass(frozen=True)
class Contract:
    number: str
    date: str = ""


@dataclass(frozen=True)
class Fa3Input:
    """Everything an FA(3) document says, already resolved."""

    seller: Party
    buyer: Party
    number: str
    issue_date: str
    currency: str
    lines: tuple[Line, ...]
    kind: str = KIND_VAT
    place_of_issue: str = ""
    delivery_date: str = ""
    period_from: str = ""
    period_to: str = ""
    # PLN per one unit of ``currency``. Required for a foreign currency invoice.
    exchange_rate: Decimal | None = None
    cash_accounting: bool = False
    self_billing: bool = False
    reverse_charge: bool = False
    split_payment: bool = False
    exemption_basis: str = ""
    correction: Correction | None = None
    advance_invoices: tuple[AdvanceInvoiceRef, ...] = ()
    order_value_gross: Decimal | None = None
    order_lines: tuple[OrderLine, ...] = ()
    contracts: tuple[Contract, ...] = ()
    due_date: str = ""
    bank_account: str = ""
    system_info: str = "OpenConstructionERP"
    generated_at: datetime | None = None
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Totals:
    """The summary the writer derives from the lines."""

    bases: dict[str, Decimal]
    vat: dict[str, Decimal]
    net: Decimal
    vat_total: Decimal
    gross: Decimal


def _money(value: Decimal) -> str:
    return format(value.quantize(CENT, rounding=ROUND_HALF_UP), "f")


def _decimal_text(value: Decimal, places: int) -> str:
    q = value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP).normalize()
    text = format(q, "f")
    return "0" if text in ("-0", "") else text


def compute_totals(lines: tuple[Line, ...] | list[Line]) -> Totals:
    """Per-rate bases and VAT, the VAT rounded once per rate group."""
    bases: dict[str, Decimal] = {}
    for line in lines:
        if line.vat_code not in RATE_FIELDS:
            raise Fa3BuildError(f"line {line.description!r}: {line.vat_code!r} is not an FA(3) tax rate code")
        # A correction shown as "before" and "after" rows: the totals are the
        # difference, so a "before" row counts against its rate.
        signed = -line.net_amount if line.state_before else line.net_amount
        base_field, _ = RATE_FIELDS[line.vat_code]
        bases[base_field] = bases.get(base_field, Decimal("0")) + signed
    vat: dict[str, Decimal] = {}
    for line in lines:
        base_field, vat_field = RATE_FIELDS[line.vat_code]
        if vat_field is not None and vat_field not in vat:
            vat[vat_field] = (bases[base_field] * rate_percent(line.vat_code) / 100).quantize(
                CENT, rounding=ROUND_HALF_UP
            )
    net = sum(bases.values(), Decimal("0")).quantize(CENT, rounding=ROUND_HALF_UP)
    vat_total = sum(vat.values(), Decimal("0"))
    return Totals(
        bases={k: v.quantize(CENT, rounding=ROUND_HALF_UP) for k, v in bases.items()},
        vat=vat,
        net=net,
        vat_total=vat_total,
        gross=net + vat_total,
    )


def _sub(parent: ET.Element, tag: str, text: str | None = None) -> ET.Element:
    el = ET.SubElement(parent, f"{{{NS}}}{tag}")
    if text is not None:
        el.text = text
    return el


def _address(parent: ET.Element, party: Party, *, tag: str = "Adres") -> None:
    if not party.address_line1.strip():
        return
    adres = _sub(parent, tag)
    _sub(adres, "KodKraju", (party.country or "PL").upper())
    _sub(adres, "AdresL1", party.address_line1.strip())
    if party.address_line2.strip():
        _sub(adres, "AdresL2", party.address_line2.strip())


def _check_party(party: Party, role: str) -> None:
    if not party.name.strip():
        raise Fa3BuildError(f"the {role} has no name")


def _check_input(data: Fa3Input) -> None:
    if data.kind not in KINDS:
        raise Fa3BuildError(f"{data.kind!r} is not an FA(3) invoice kind; use one of {', '.join(KINDS)}")
    _check_party(data.seller, "seller")
    _check_party(data.buyer, "buyer")
    if not data.seller.nip.strip():
        raise Fa3BuildError("the seller has no NIP; set the registration's tax registration id")
    if not data.seller.address_line1.strip():
        raise Fa3BuildError("the seller has no address; set the issuer address in the KSeF settings")
    if not data.number.strip():
        raise Fa3BuildError("the invoice has no number")
    try:
        date.fromisoformat(data.issue_date)
    except ValueError as exc:
        raise Fa3BuildError(f"the issue date {data.issue_date!r} is not an ISO date") from exc
    if data.currency.upper() != "PLN" and (data.exchange_rate is None or data.exchange_rate <= 0):
        raise Fa3BuildError(
            f"the invoice is in {data.currency}; FA(3) states the VAT in PLN as well, so it needs the exchange rate"
        )
    if data.kind in CORRECTION_KINDS:
        if data.correction is None or not data.correction.corrected:
            raise Fa3BuildError("a corrective invoice names the invoice it corrects (number, date, KSeF number)")
        if data.correction.type not in (1, 2, 3):
            raise Fa3BuildError("the correction type is 1, 2 or 3")
    if data.kind in ADVANCE_KINDS and data.order_value_gross is None:
        raise Fa3BuildError("an advance invoice states the value of the order or contract it is paid against")
    if data.kind not in ADVANCE_KINDS and not data.lines:
        raise Fa3BuildError("the invoice has no lines")
    if any(line.vat_code == "zw" for line in data.lines) and not data.exemption_basis.strip():
        raise Fa3BuildError("an exempt line needs the legal basis of the exemption (P_19A)")


def build_xml(data: Fa3Input) -> str:
    """The FA(3) document for ``data``, as UTF-8 XML text."""
    _check_input(data)
    totals = compute_totals(data.lines)
    foreign = data.currency.upper() != "PLN"

    ET.register_namespace("", NS)
    root = ET.Element(f"{{{NS}}}Faktura")

    naglowek = _sub(root, "Naglowek")
    kod = _sub(naglowek, "KodFormularza", FA3.form_value)
    kod.set("kodSystemowy", FA3.system_code)
    kod.set("wersjaSchemy", FA3.schema_version)
    _sub(naglowek, "WariantFormularza", FA3.variant)
    generated = (data.generated_at or datetime.now(UTC)).astimezone(UTC).replace(microsecond=0)
    _sub(naglowek, "DataWytworzeniaFa", generated.strftime("%Y-%m-%dT%H:%M:%SZ"))
    if data.system_info:
        _sub(naglowek, "SystemInfo", data.system_info[:256])

    podmiot1 = _sub(root, "Podmiot1")
    dane1 = _sub(podmiot1, "DaneIdentyfikacyjne")
    _sub(dane1, "NIP", data.seller.nip.strip())
    _sub(dane1, "Nazwa", data.seller.name.strip()[:512])
    _address(podmiot1, data.seller)
    if data.seller.email.strip():
        _sub(_sub(podmiot1, "DaneKontaktowe"), "Email", data.seller.email.strip())

    podmiot2 = _sub(root, "Podmiot2")
    dane2 = _sub(podmiot2, "DaneIdentyfikacyjne")
    buyer = data.buyer
    if buyer.nip.strip():
        _sub(dane2, "NIP", buyer.nip.strip())
    elif buyer.eu_vat.strip():
        _sub(dane2, "KodUE", buyer.eu_country.strip().upper())
        _sub(dane2, "NrVatUE", buyer.eu_vat.strip())
    elif buyer.other_id.strip():
        if buyer.other_country.strip():
            _sub(dane2, "KodKraju", buyer.other_country.strip().upper())
        _sub(dane2, "NrID", buyer.other_id.strip())
    else:
        _sub(dane2, "BrakID", "1")
    _sub(dane2, "Nazwa", buyer.name.strip()[:512])
    _address(podmiot2, buyer)
    if buyer.email.strip():
        _sub(_sub(podmiot2, "DaneKontaktowe"), "Email", buyer.email.strip())
    # Not a unit of a local government, not a member of a VAT group. Both
    # markers are mandatory in FA(3); the platform does not model either case.
    _sub(podmiot2, "JST", "2")
    _sub(podmiot2, "GV", "2")

    fa = _sub(root, "Fa")
    _sub(fa, "KodWaluty", data.currency.upper())
    _sub(fa, "P_1", data.issue_date)
    if data.place_of_issue.strip():
        _sub(fa, "P_1M", data.place_of_issue.strip())
    _sub(fa, "P_2", data.number.strip())
    if data.period_from and data.period_to:
        okres = _sub(fa, "OkresFa")
        _sub(okres, "P_6_Od", data.period_from)
        _sub(okres, "P_6_Do", data.period_to)
    elif data.delivery_date and data.delivery_date != data.issue_date:
        _sub(fa, "P_6", data.delivery_date)

    for base_field, vat_field in _SUMMARY_ORDER:
        if base_field not in totals.bases:
            continue
        _sub(fa, base_field, _money(totals.bases[base_field]))
        if vat_field is not None:
            vat_amount = totals.vat.get(vat_field, Decimal("0"))
            _sub(fa, vat_field, _money(vat_amount))
            if foreign:
                _sub(fa, f"{vat_field}W", _money(vat_amount * (data.exchange_rate or Decimal("0"))))
    _sub(fa, "P_15", _money(totals.gross))
    if foreign and data.kind in ADVANCE_KINDS:
        _sub(fa, "KursWalutyZ", _decimal_text(data.exchange_rate or Decimal("0"), 6))

    adnotacje = _sub(fa, "Adnotacje")
    _sub(adnotacje, "P_16", "1" if data.cash_accounting else "2")
    _sub(adnotacje, "P_17", "1" if data.self_billing else "2")
    _sub(adnotacje, "P_18", "1" if data.reverse_charge else "2")
    _sub(adnotacje, "P_18A", "1" if data.split_payment else "2")
    zwolnienie = _sub(adnotacje, "Zwolnienie")
    if data.exemption_basis.strip() and any(line.vat_code == "zw" for line in data.lines):
        _sub(zwolnienie, "P_19", "1")
        _sub(zwolnienie, "P_19A", data.exemption_basis.strip()[:256])
    else:
        _sub(zwolnienie, "P_19N", "1")
    _sub(_sub(adnotacje, "NoweSrodkiTransportu"), "P_22N", "1")
    _sub(adnotacje, "P_23", "2")
    _sub(_sub(adnotacje, "PMarzy"), "P_PMarzyN", "1")

    _sub(fa, "RodzajFaktury", data.kind)

    if data.kind in CORRECTION_KINDS and data.correction is not None:
        if data.correction.reason.strip():
            _sub(fa, "PrzyczynaKorekty", data.correction.reason.strip()[:256])
        _sub(fa, "TypKorekty", str(data.correction.type))
        for original in data.correction.corrected:
            dane = _sub(fa, "DaneFaKorygowanej")
            _sub(dane, "DataWystFaKorygowanej", original.issue_date)
            _sub(dane, "NrFaKorygowanej", original.number)
            if original.ksef_number.strip():
                _sub(dane, "NrKSeF", "1")
                _sub(dane, "NrKSeFFaKorygowanej", original.ksef_number.strip())
            else:
                _sub(dane, "NrKSeFN", "1")

    if data.kind in (KIND_ROZ, KIND_KOR_ROZ):
        for advance in data.advance_invoices:
            ref = _sub(fa, "FakturaZaliczkowa")
            if advance.ksef_number.strip():
                _sub(ref, "NrKSeFFaZaliczkowej", advance.ksef_number.strip())
            else:
                _sub(ref, "NrKSeFZN", "1")
                _sub(ref, "NrFaZaliczkowej", advance.number)

    if data.kind not in ADVANCE_KINDS:
        for index, line in enumerate(data.lines, start=1):
            wiersz = _sub(fa, "FaWiersz")
            _sub(wiersz, "NrWierszaFa", str(index))
            if line.delivery_date:
                _sub(wiersz, "P_6A", line.delivery_date)
            _sub(wiersz, "P_7", line.description.strip()[:512] or "-")
            if line.pkwiu.strip():
                _sub(wiersz, "PKWiU", line.pkwiu.strip())
            if line.unit.strip():
                _sub(wiersz, "P_8A", line.unit.strip())
            _sub(wiersz, "P_8B", _decimal_text(line.quantity, 6))
            _sub(wiersz, "P_9A", _decimal_text(line.unit_net_price, 8))
            _sub(wiersz, "P_11", _money(line.net_amount))
            _sub(wiersz, "P_12", line.vat_code)
            if line.annex_15:
                _sub(wiersz, "P_12_Zal_15", "1")
            if line.gtu.strip():
                _sub(wiersz, "GTU", line.gtu.strip())
            if line.state_before:
                _sub(wiersz, "StanPrzed", "1")

    if data.due_date or data.bank_account:
        platnosc = _sub(fa, "Platnosc")
        if data.due_date:
            _sub(_sub(platnosc, "TerminPlatnosci"), "Termin", data.due_date)
        if data.bank_account:
            _sub(platnosc, "FormaPlatnosci", "6")
            _sub(_sub(platnosc, "RachunekBankowy"), "NrRB", data.bank_account.replace(" ", ""))

    if data.contracts:
        warunki = _sub(fa, "WarunkiTransakcji")
        for contract in data.contracts:
            umowa = _sub(warunki, "Umowy")
            if contract.date:
                _sub(umowa, "DataUmowy", contract.date)
            if contract.number.strip():
                _sub(umowa, "NrUmowy", contract.number.strip()[:256])

    if data.kind in ADVANCE_KINDS:
        zamowienie = _sub(fa, "Zamowienie")
        _sub(zamowienie, "WartoscZamowienia", _money(data.order_value_gross or Decimal("0")))
        order_lines = data.order_lines or tuple(
            OrderLine(
                description=line.description,
                quantity=line.quantity,
                unit=line.unit,
                unit_net_price=line.unit_net_price,
                net_amount=line.net_amount,
                vat_amount=(line.net_amount * rate_percent(line.vat_code) / 100).quantize(CENT, ROUND_HALF_UP),
                vat_code=line.vat_code,
                annex_15=line.annex_15,
            )
            for line in data.lines
        )
        if not order_lines:
            raise Fa3BuildError("an advance invoice lists the lines of the order or contract")
        for index, order_line in enumerate(order_lines, start=1):
            zw = _sub(zamowienie, "ZamowienieWiersz")
            _sub(zw, "NrWierszaZam", str(index))
            _sub(zw, "P_7Z", order_line.description.strip()[:512] or "-")
            if order_line.unit.strip():
                _sub(zw, "P_8AZ", order_line.unit.strip())
            _sub(zw, "P_8BZ", _decimal_text(order_line.quantity, 6))
            _sub(zw, "P_9AZ", _decimal_text(order_line.unit_net_price, 8))
            _sub(zw, "P_11NettoZ", _money(order_line.net_amount))
            _sub(zw, "P_11VatZ", _money(order_line.vat_amount))
            _sub(zw, "P_12Z", order_line.vat_code)
            if order_line.annex_15:
                _sub(zw, "P_12Z_Zal_15", "1")

    body = ET.tostring(root, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + body


# ── Reading ──────────────────────────────────────────────────────────────────


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


@dataclass(frozen=True)
class Summary:
    """What the rules need from an FA(3) (or older) document."""

    namespace: str
    system_code: str
    issue_date: str
    number: str
    seller_nip: str
    # Empty when the buyer has no Polish NIP (EU VAT number, other id, or none).
    buyer_nip: str
    currency: str
    kind: str
    gross: Decimal | None
    split_payment: bool
    annex_15_lines: int
    vat_codes: tuple[str, ...]
    corrected_ksef_numbers: tuple[str, ...]


def read_summary(text: str) -> Summary:
    """Read the facts the rules check. Raises :class:`Fa3BuildError` for unreadable XML."""
    try:
        root = SafeET.fromstring((text or "").encode("utf-8"))
    except Exception as exc:  # noqa: BLE001 - any parse failure is the same answer
        raise Fa3BuildError(f"the document is not readable XML: {exc}") from exc
    namespace = _ns(root.tag)

    def first(path: tuple[str, ...]) -> str:
        node = root
        for name in path:
            node = next((c for c in node if _local(c.tag) == name), None)
            if node is None:
                return ""
        return (node.text or "").strip()

    kod = next((c for n in root if _local(n.tag) == "Naglowek" for c in n if _local(c.tag) == "KodFormularza"), None)
    fa = next((c for c in root if _local(c.tag) == "Fa"), None)
    annex = 0
    codes: list[str] = []
    corrected: list[str] = []
    if fa is not None:
        for wiersz in (c for c in fa if _local(c.tag) == "FaWiersz"):
            for item in wiersz:
                name = _local(item.tag)
                if name == "P_12_Zal_15" and (item.text or "").strip() == "1":
                    annex += 1
                elif name == "P_12":
                    codes.append((item.text or "").strip())
        for zam in (c for c in fa if _local(c.tag) == "Zamowienie"):
            for zw in zam:
                if any(_local(i.tag) == "P_12Z_Zal_15" and (i.text or "").strip() == "1" for i in zw):
                    annex += 1
        for dane in (c for c in fa if _local(c.tag) == "DaneFaKorygowanej"):
            for item in dane:
                if _local(item.tag) == "NrKSeFFaKorygowanej" and (item.text or "").strip():
                    corrected.append((item.text or "").strip())
    gross_text = first(("Fa", "P_15"))
    try:
        gross = Decimal(gross_text) if gross_text else None
    except ArithmeticError:
        gross = None
    return Summary(
        namespace=namespace,
        system_code=(kod.get("kodSystemowy") or "").strip() if kod is not None else "",
        issue_date=first(("Fa", "P_1")),
        number=first(("Fa", "P_2")),
        seller_nip=first(("Podmiot1", "DaneIdentyfikacyjne", "NIP")),
        buyer_nip=first(("Podmiot2", "DaneIdentyfikacyjne", "NIP")),
        currency=first(("Fa", "KodWaluty")),
        kind=first(("Fa", "RodzajFaktury")),
        gross=gross,
        split_payment=first(("Fa", "Adnotacje", "P_18A")) == "1",
        annex_15_lines=annex,
        vat_codes=tuple(codes),
        corrected_ksef_numbers=tuple(corrected),
    )


__all__ = [
    "ADVANCE_KINDS",
    "CORRECTION_KINDS",
    "KINDS",
    "KIND_KOR",
    "KIND_KOR_ROZ",
    "KIND_KOR_ZAL",
    "KIND_ROZ",
    "KIND_VAT",
    "KIND_ZAL",
    "MEDIA_TYPE",
    "NS",
    "RATE_FIELDS",
    "VAT_CODES",
    "AdvanceInvoiceRef",
    "Contract",
    "CorrectedInvoice",
    "Correction",
    "Fa3BuildError",
    "Fa3Input",
    "Line",
    "OrderLine",
    "Party",
    "Summary",
    "Totals",
    "build_xml",
    "compute_totals",
    "rate_percent",
    "read_summary",
]
