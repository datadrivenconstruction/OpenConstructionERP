# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rules for the UBL-TR invoice, run before anything is exported.

The accountant must learn what is wrong and why while the invoice is still on
the screen, not from an integrator's rejection a day later. :func:`check_tr`
returns one :class:`~app.modules.einvoice.rules.RuleViolation` per finding,
with a stable rule id the frontend localises and the values the message
quotes in ``params``.

Three sources feed the rules, and each rule says which one it restates:

* the official Schematron (``UBL-TR_Common_Schematron.xml`` and
  ``UBL-TR_Main_Schematron.xml`` of the e-Fatura package, revision
  2026-07-01, https://ebelge.gib.gov.tr/efaturamevzuat.html). A document that
  breaks one of these is rejected by GİB;
* the XSD of the UBL-TR 1.2.1 package, for what is mandatory;
* this platform, for everything the Schematron leaves alone. It contains no
  arithmetic at all, so every sum invariant (the TR-SUM family) is ours, read
  off the three official withholding samples.

The code lists below are copies of the value lists in ``UBL-TR_Codelist.xml``
of the same package, same revision. They are data: when GİB publishes a new
revision they are replaced wholesale, never patched by hand.

Supported today: profiles TEMELFATURA, TICARIFATURA and EARSIVFATURA, invoice
types SATIS, TEVKIFAT, IADE and ISTISNA. Everything else GİB defines is
refused by name (TR-PROFILE-01, TR-TYPE-01) rather than written wrongly.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from decimal import Decimal

from app.core.currency_registry import minor_units, money_quantum
from app.modules.einvoice.rules import FATAL, WARNING, RuleViolation
from app.modules.einvoice.tr_ids import (
    classify_tax_number,
    is_valid_document_id,
    is_valid_tax_number,
    is_valid_uuid,
)
from app.modules.einvoice.ubl_tr import (
    CUSTOMIZATION_IDS,
    TrDocumentRef,
    TrInvoice,
    TrParty,
    TrTaxGroup,
    document_vat_computed,
    document_vat_withheld,
    has_withholding,
    tr_unit_code,
    withholding_percent,
)

# ── code lists (UBL-TR_Codelist.xml, revision 2026-07-01) ────────────────────


def _codes(*chunks: str) -> frozenset[str]:
    return frozenset(" ".join(chunks).split())


# ProfileIDType plus ProfileIDTypeEarchive: every scenario GİB defines.
KNOWN_PROFILES = _codes(
    "TICARIFATURA TEMELFATURA YOLCUBERABERFATURA IHRACAT OZELFATURA KAMU HKS ENERJI ILAC_TIBBICIHAZ",
    "YATIRIMTESVIK IDIS EARSIVFATURA",
)
SUPPORTED_PROFILES = _codes("TEMELFATURA TICARIFATURA EARSIVFATURA")

# InvoiceTypeCodeList.
KNOWN_INVOICE_TYPES = _codes(
    "SATIS IADE TEVKIFAT TEVKIFATIADE ISTISNA OZELMATRAH IHRACKAYITLI SGK KOMISYONCU HKSSATIS HKSKOMISYONCU",
    "KONAKLAMAVERGISI SARJ SARJANLIK TEKNOLOJIDESTEK YTBSATIS YTBIADE YTBISTISNA YTBTEVKIFAT YTBTEVKIFATIADE",
)
SUPPORTED_INVOICE_TYPES = _codes("SATIS TEVKIFAT IADE ISTISNA")

# ``InvoiceTypeCodeCheck``: a return invoice is allowed in these scenarios only.
# Of the three supported here that leaves TICARIFATURA out, where a return goes
# through the reject or return response instead.
_IADE_PROFILES = _codes("TEMELFATURA EARSIVFATURA ILAC_TIBBICIHAZ YATIRIMTESVIK IDIS KAMU")

# ``GeneralWithholdingTaxTotalCheck``: the types that may carry a withholding
# block, narrowed to the types supported here.
_WITHHOLDING_TYPES = _codes("TEVKIFAT IADE")

# WithholdingTaxType.
WITHHOLDING_CODES = _codes(
    "601 602 603 604 605 606 607 608 609 610 611 612 613 614 615 616 617 618 619 620 621 622 623 624 625 626",
    "627 801 802 803 804 805 806 807 808 809 810 811 812 813 814 815 816 817 818 819 820 821 822 823 824 825",
)

# WithholdingTaxTypeWithPercent: the code and the percent written one after the
# other, which is exactly how the Schematron looks a pair up. Some codes keep a
# superseded fraction beside the current one (601 with 30 and with 40); the
# list says what GİB accepts, the statutory data says what applies on a date.
WITHHOLDING_CODE_PERCENT_PAIRS = _codes(
    "60130 60140 60290 60350 60370 60450 60550 60690 60790 60890 60950 60970 61090 61190 61270 61290 61370",
    "61390 61450 61550 61570 61650 61770 61870 61970 62070 62190 62290 62350 62420 62530 62620 65090 65050",
    "65070 65020 65030 62740 62750 801100 802100 803100 804100 805100 806100 807100 808100 809100 810100",
    "811100 812100 813100 814100 815100 816100 817100 818100 819100 820100 821100 822100 823100 824100",
    "825100",
)

# TaxExemptionReasonCodeType: every code accepted in the three supported
# scenarios. (308 and 339 belong to the investment incentive scenario only.)
EXEMPTION_REASON_CODES = _codes(
    "001 101 102 103 104 105 106 107 108 151 201 202 204 205 206 207 208 209 211 212 213 214 215 216 217 218",
    "219 220 221 223 225 226 227 228 229 230 231 232 233 234 235 236 237 238 239 240 241 242 250 301 302 303",
    "304 305 306 307 309 310 311 312 313 314 315 316 317 318 319 320 321 322 323 324 325 326 327 328 329 330",
    "331 332 333 334 335 336 337 338 340 341 342 343 344 350 351 501 555 801 802 803 804 805 806 807 808 809",
    "810 811 812 701 702 703 704",
)

# istisnaTaxExemptionReasonCodeType: codes that need invoice type ISTISNA (or a
# return). Intersected with the list above when used.
ISTISNA_REASON_CODES = _codes(
    "001 101 102 103 104 105 106 107 108 201 202 204 205 206 207 208 209 211 212 213 214 215 216 217 218 219",
    "220 221 223 225 226 227 228 229 230 231 232 233 234 235 236 237 238 239 240 241 242 250 301 302 303 304",
    "305 306 307 308 309 310 311 312 313 314 315 316 317 318 319 320 321 322 323 324 325 326 327 328 329 330",
    "331 332 333 334 335 336 337 338 339 340 341 342 343 344 350 501",
)
# ozelMatrahTaxExemptionReasonCodeType and ihracExemptionReasonCodeType: codes
# of two invoice types that are not supported here, allowed on a return only.
_OTHER_TYPE_REASON_CODES = _codes("801 802 803 804 805 806 807 808 809 810 811 812 701 702 703 704")
# The code for sales outside the VAT rate check. ``DemirbasKDVTaxExemptionCheck``.
_REASON_CODE_555 = "555"

# PaymentMeansCodeTypeList (UN/EDIFACT 4461 as GİB accepts it).
PAYMENT_MEANS_CODES = _codes(
    "1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33 34 35 36 37",
    "38 39 40 41 42 43 44 45 46 47 48 49 50 51 52 53 60 61 62 63 64 65 66 67 70 74 75 76 77 78 91 92 93 94",
    "95 96 97 ZZZ",
)

# ChannelCodeList.
PAYMENT_CHANNEL_CODES = _codes(
    "AA AB AC AD AE AF AG AH AI AJ AK AL AM AN AO AP AQ AR AS AT AU CA EI EM EX FT FX GM IE IM MA PB PS SW",
    "TE TG TL TM TT TX XF XG XH XI XJ",
)

# PartyIdentificationIDType less VKN and TCKN, which are never "extra".
PARTY_ID_SCHEMES = _codes(
    "HIZMETNO MUSTERINO TESISATNO TELEFONNO DISTRIBUTORNO TICARETSICILNO TAPDKNO BAYINO ABONENO",
    "SAYACNO EPDKNO SUBENO PASAPORTNO ARACIKURUMETIKET ARACIKURUMVKN CIFTCINO IMALATCINO DOSYANO HASTANO",
    "MERSISNO URETICINO GTB_REFNO GTB_GCB_TESCILNO GTB_FIILI_IHRACAT_TARIHI ARACKIMLIKNO PLAKA SEVKIYATNO",
)

# CurrencyCodeList.
CURRENCY_CODES = _codes(
    "AED AFN ALL AMD ANG AOA ARS AUD AWG AZN BAM BBD BDT BGN BHD BIF BMD BND BOB BOV BRL BSD BTN BWP BYN BZD",
    "CAD CDF CHE CHF CHW CLF CLP CNY COP COU CRC CUC CUP CVE CZK DJF DKK DOP DZD EEK EGP ERN ETB EUR FJD FKP",
    "GBP GEL GHS GIP GMD GNF GTQ GWP GYD HKD HNL HRK HTG HUF IDR ILS INR IQD IRR ISK JMD JOD JPY KES KGS KHR",
    "KMF KPW KRW KWD KYD KZT LAK LBP LKR LRD LSL LTL LVL LYD MAD MDL MGA MKD MMK MNT MOP MRU MUR MVR MWK MXN",
    "MXV MYR MZN NAD NGN NIO NOK NPR NZD OMR PAB PEN PGK PHP PKR PLN PYG QAR RON RSD RUB RWF SAR SBD SCR SDG",
    "SEK SGD SHP SLE SLL SOS SRD SSP STD STN SVC SYP SZL THB TJS TMT TND TOP TRY TTD TWD TZS UAH UGX USD USN",
    "USS UYI UYU UYW UZS VEF VND VUV WST XAD XAF XAG XAU XBA XBB XBC XBD XCD XCG XDR XFU XOF XPD XPF XPT XSU",
    "XTS XUA XXX VED VES YER ZAR ZMK ZMW ZWG ZWL",
)

# CountryCodeList.
COUNTRY_CODES = _codes(
    "AF AX AL DZ AS AD AO AI AQ AG AR AM AW AU AT AZ BS BH BD BB BY BE BZ BJ BM BT BO BA BW BV BR IO BN BG",
    "BF BI KH CM CA CV KY CF TD CL CW CN CX CC CO KM CG CD CK CR CI HR CU CY CZ DK DJ DM DO EC EG SV GQ ER",
    "EE ET FK FO FJ FI FR GF PF TF GA GM GE DE GH GI GR GL GD GP GU GT GG GN GW GY HT HM VA HN HK HU IS IN",
    "ID IR IQ IE IM IL IT JM JP JE JO KZ KE KI KP KR KW KG LA LV LB LS LR LY LI LT LU MO MK MG MW MY MV ML",
    "MT MH MQ MR MU YT MX FM MD MC MN ME MS MA MZ MM NA NR NP NL AN NC NZ NI NE NG NU NF MP NO OM PK PW PS",
    "PA PG PY PE PH PN PL PT PR QA RE RO RU RW BL SH KN LC MF PM VC WS SM ST SA SN RS SC SL SG SK SI SB SO",
    "ZA GS ES LK SD SR SJ SZ SE CH SY TW TJ TZ TH TL TG TK TO TT TN TR TM TC TV UG UA AE GB US UM UY UZ VU",
    "VE VN VG VI WF EH YE ZM ZW CTR XK BQ SX ZZ XZ SS",
)

# ``TimeCheck``: the issue date may not precede this day.
EARLIEST_ISSUE_DATE = dt.date(2005, 1, 1)
# ``decimalCheck``: at most fifteen digits before the point.
_AMOUNT_LIMIT = Decimal(10) ** 15
# ``CurrencyCodeCheck``: the exchange rate may carry six decimals.
_RATE_QUANTUM = Decimal("0.000001")
# GİB compares the issue date with its own calendar day. Türkiye keeps one
# offset all year, so the day there is the day at UTC+3.
_TR_OFFSET = dt.timezone(dt.timedelta(hours=3))

_SUPPLIER_HOME = "in the e-invoice settings"
_CUSTOMER_HOME = "on the contact this invoice bills"
_INVOICE_HOME = "on this invoice"


def _v(rule_id: str, severity: str, message: str, term: str, **params: object) -> RuleViolation:
    return RuleViolation(rule_id, severity, message, term, {key: str(value) for key, value in params.items()})


def _q(value: Decimal, currency: str) -> Decimal:
    return value.quantize(money_quantum(currency))


def _same(left: Decimal, right: Decimal, currency: str) -> bool:
    return _q(left, currency) == _q(right, currency)


def _fmt(value: Decimal, currency: str) -> str:
    return f"{_q(value, currency)} {currency}"


def today_in_turkiye() -> dt.date:
    """The calendar day in Türkiye, which is the day GİB checks an issue date against."""
    return dt.datetime.now(_TR_OFFSET).date()


# ── header ───────────────────────────────────────────────────────────────────


def _check_header(inv: TrInvoice, today: dt.date) -> list[RuleViolation]:
    out: list[RuleViolation] = []

    # TR-PROFILE-01 (``ProfileIDCheck``).
    if inv.profile_id not in KNOWN_PROFILES:
        out.append(
            _v(
                "TR-PROFILE-01",
                FATAL,
                f"{inv.profile_id!r} is not an e-Fatura scenario. Choose TEMELFATURA, TICARIFATURA or "
                f"EARSIVFATURA {_INVOICE_HOME}.",
                "ProfileID",
                profile=inv.profile_id,
            )
        )
    elif inv.profile_id not in SUPPORTED_PROFILES:
        out.append(
            _v(
                "TR-PROFILE-01",
                FATAL,
                f"The scenario {inv.profile_id} is not supported yet. This platform writes TEMELFATURA, "
                "TICARIFATURA and EARSIVFATURA documents; issue this one from the integrator's portal.",
                "ProfileID",
                profile=inv.profile_id,
            )
        )

    # TR-TYPE-01 (``InvoiceTypeCodeCheck``).
    if inv.invoice_type not in KNOWN_INVOICE_TYPES:
        out.append(
            _v(
                "TR-TYPE-01",
                FATAL,
                f"{inv.invoice_type!r} is not an e-Fatura invoice type. Choose SATIS, TEVKIFAT, IADE or "
                f"ISTISNA {_INVOICE_HOME}.",
                "InvoiceTypeCode",
                invoice_type=inv.invoice_type,
            )
        )
    elif inv.invoice_type not in SUPPORTED_INVOICE_TYPES:
        out.append(
            _v(
                "TR-TYPE-01",
                FATAL,
                f"The invoice type {inv.invoice_type} is not supported yet. This platform writes SATIS, "
                "TEVKIFAT, IADE and ISTISNA invoices; issue this one from the integrator's portal.",
                "InvoiceTypeCode",
                invoice_type=inv.invoice_type,
            )
        )

    # TR-PROFILE-02 (``InvoiceTypeCodeCheck``, second assertion).
    if inv.invoice_type == "IADE" and inv.profile_id in SUPPORTED_PROFILES and inv.profile_id not in _IADE_PROFILES:
        out.append(
            _v(
                "TR-PROFILE-02",
                FATAL,
                f"A return invoice (IADE) cannot be issued in the {inv.profile_id} scenario. Use TEMELFATURA "
                "or EARSIVFATURA, or return the original through the buyer's reject or return response.",
                "ProfileID",
                profile=inv.profile_id,
                invoice_type=inv.invoice_type,
            )
        )

    # TR-HDR-01 (``CustomizationIDCheck``).
    if inv.customization_id not in CUSTOMIZATION_IDS:
        out.append(
            _v(
                "TR-HDR-01",
                FATAL,
                f"The customisation identifier must be TR1.2 or TR1.2.1, not {inv.customization_id!r}.",
                "CustomizationID",
                customization_id=inv.customization_id,
            )
        )

    # TR-ID-01 (``InvoiceIDCheck``). An empty ID is a statement that the
    # integrator numbers the document, and is only worth a word.
    if not inv.document_id:
        out.append(
            _v(
                "TR-ID-01",
                WARNING,
                "The invoice has no e-Fatura document ID, so the file is written with an empty ID for the "
                "integrator to assign. If you number the documents yourself, enter the 16 character ID "
                f"{_INVOICE_HOME}.",
                "ID",
            )
        )
    elif not is_valid_document_id(inv.document_id):
        out.append(
            _v(
                "TR-ID-01",
                FATAL,
                f"The document ID {inv.document_id!r} is not a valid e-Fatura ID. It must be 16 characters: "
                "3 capital letters or digits for the series, the 4 digit year, then a 9 digit sequence, as "
                "in ABC2026000000001.",
                "ID",
                document_id=inv.document_id,
            )
        )

    # TR-ID-02 (``UUIDCheck``).
    if not is_valid_uuid(inv.uuid):
        out.append(
            _v(
                "TR-ID-02",
                FATAL,
                f"The invoice UUID (ETTN) {inv.uuid!r} is not in the 8-4-4-4-12 hexadecimal form.",
                "UUID",
                uuid=inv.uuid,
            )
        )

    # TR-DATE-01 (``TimeCheck``).
    if inv.issue_date > today:
        out.append(
            _v(
                "TR-DATE-01",
                FATAL,
                f"The issue date {inv.issue_date.isoformat()} is in the future. GİB rejects an invoice dated "
                f"after the day it is sent ({today.isoformat()}).",
                "IssueDate",
                issue_date=inv.issue_date.isoformat(),
                today=today.isoformat(),
            )
        )
    elif inv.issue_date < EARLIEST_ISSUE_DATE:
        out.append(
            _v(
                "TR-DATE-01",
                FATAL,
                f"The issue date {inv.issue_date.isoformat()} is before {EARLIEST_ISSUE_DATE.isoformat()}, "
                "the earliest date GİB accepts.",
                "IssueDate",
                issue_date=inv.issue_date.isoformat(),
                earliest=EARLIEST_ISSUE_DATE.isoformat(),
            )
        )
    return out


# ── currency and amounts ─────────────────────────────────────────────────────


def _check_currency(inv: TrInvoice) -> list[RuleViolation]:
    out: list[RuleViolation] = []
    currency = inv.currency

    # TR-CUR-02 (``CurrencyCodeCheck``, ``GeneralCurrencyIDCheck``, ``decimalCheck``).
    if currency not in CURRENCY_CODES:
        out.append(
            _v(
                "TR-CUR-02",
                FATAL,
                f"{currency!r} is not a currency code GİB accepts. Use the ISO 4217 code, for example TRY, EUR or USD.",
                "DocumentCurrencyCode",
                currency=currency,
            )
        )
    elif minor_units(currency) > 2:
        out.append(
            _v(
                "TR-CUR-02",
                FATAL,
                f"{currency} amounts have {minor_units(currency)} decimals and an e-Fatura amount may carry "
                "2 at most. Invoice in a currency with two decimals or fewer.",
                "DocumentCurrencyCode",
                currency=currency,
                decimals=minor_units(currency),
            )
        )

    # TR-CUR-01 (``CurrencyCodeCheck``, the exchange rate assertions).
    rate = inv.exchange_rate
    if currency != "TRY" and rate is None:
        out.append(
            _v(
                "TR-CUR-01",
                FATAL,
                f"The invoice is in {currency}, so it must state the exchange rate to Turkish lira. Enter "
                f"the rate {_INVOICE_HOME}.",
                "PricingExchangeRate/CalculationRate",
                currency=currency,
            )
        )
    elif rate is not None and (rate <= 0 or rate >= _AMOUNT_LIMIT or rate != rate.quantize(_RATE_QUANTUM)):
        out.append(
            _v(
                "TR-CUR-01",
                FATAL,
                f"The exchange rate {rate} cannot be written. It must be positive, with at most 15 digits "
                "before the decimal point and 6 after.",
                "PricingExchangeRate/CalculationRate",
                rate=rate,
            )
        )
    return out


def _amounts(inv: TrInvoice) -> Iterable[tuple[str, Decimal | None]]:
    totals = inv.totals
    yield "LegalMonetaryTotal/LineExtensionAmount", totals.line_extension
    yield "LegalMonetaryTotal/TaxExclusiveAmount", totals.tax_exclusive
    yield "LegalMonetaryTotal/TaxInclusiveAmount", totals.tax_inclusive
    yield "LegalMonetaryTotal/AllowanceTotalAmount", totals.allowance_total
    yield "LegalMonetaryTotal/ChargeTotalAmount", totals.charge_total
    yield "LegalMonetaryTotal/PayableAmount", totals.payable
    for item in inv.allowance_charges:
        yield "AllowanceCharge/Amount", item.amount
    for group in inv.tax_groups:
        yield f"TaxSubtotal[{group.key}]/TaxableAmount", group.taxable_amount
        for figure in (group.taxes.vat_computed, group.taxes.vat_withheld, group.taxes.vat_payable):
            yield f"TaxSubtotal[{group.key}]/{figure.kind}", figure.amount
    for line in inv.lines:
        yield f"InvoiceLine[{line.line_id}]/LineExtensionAmount", line.line_amount
        yield f"InvoiceLine[{line.line_id}]/Price/PriceAmount", line.unit_price
        yield f"InvoiceLine[{line.line_id}]/TaxTotal", line.vat_amount
        yield f"InvoiceLine[{line.line_id}]/WithholdingTaxTotal", line.vat_withheld
        yield f"InvoiceLine[{line.line_id}]/TaxTotal/TaxAmount", line.vat_payable
        for item in line.allowances:
            yield f"InvoiceLine[{line.line_id}]/AllowanceCharge/Amount", item.amount


def _check_amounts(inv: TrInvoice) -> list[RuleViolation]:
    """TR-AMT-01 (``decimalCheck``): amounts are written unsigned, fifteen digits at most.

    A return invoice states what is returned as positive amounts under the
    type IADE; nothing on an e-Fatura is negative.
    """
    out: list[RuleViolation] = []
    for term, value in _amounts(inv):
        if value is None:
            continue
        if value < 0:
            out.append(
                _v(
                    "TR-AMT-01",
                    FATAL,
                    f"The amount {value} at {term} is negative. An e-Fatura carries no negative amounts: a "
                    "return is issued as an IADE invoice with positive amounts.",
                    term,
                    amount=value,
                )
            )
        elif value >= _AMOUNT_LIMIT:
            out.append(
                _v(
                    "TR-AMT-01",
                    FATAL,
                    f"The amount {value} at {term} is too large to write: an e-Fatura amount has at most 15 "
                    "digits before the decimal point.",
                    term,
                    amount=value,
                )
            )
    return out


# ── parties ──────────────────────────────────────────────────────────────────


def _check_party(party: TrParty, role: str, home: str, wrapper: str) -> list[RuleViolation]:
    out: list[RuleViolation] = []
    kind = classify_tax_number(party.tax_number)

    # TR-PARTY-01 (``PartyIdentificationTCKNVKNCheck``,
    # ``PartyIdentificationPartyNamePersonCheck``): exactly one of VKN, TCKN.
    if kind is None:
        out.append(
            _v(
                "TR-PARTY-01",
                FATAL,
                f"The {role}'s tax number {party.tax_number!r} is neither a VKN (10 digits) nor a TCKN "
                f"(11 digits). Enter the digits only, without spaces or a country prefix, {home}.",
                f"{wrapper}/PartyIdentification/ID",
                role=role,
                tax_number=party.tax_number,
            )
        )
    # TR-PARTY-02: ours. The Schematron tests the length only.
    elif not is_valid_tax_number(party.tax_number):
        out.append(
            _v(
                "TR-PARTY-02",
                FATAL,
                f"The {role}'s {kind} {party.tax_number} fails its check digit, so it is most likely "
                f"mistyped. Correct it {home}.",
                f"{wrapper}/PartyIdentification/ID",
                role=role,
                kind=kind,
                tax_number=party.tax_number,
            )
        )

    # TR-PARTY-03 (``PartyIdentificationPartyNamePersonCheck``).
    if kind == "VKN" and not party.name.strip():
        out.append(
            _v(
                "TR-PARTY-03",
                FATAL,
                f"The {role} is identified by a VKN, so the registered name is required. Enter it {home}.",
                f"{wrapper}/PartyName/Name",
                role=role,
            )
        )
    if kind == "TCKN" and not (party.first_name.strip() and party.family_name.strip()):
        out.append(
            _v(
                "TR-PARTY-03",
                FATAL,
                f"The {role} is identified by a TCKN, which belongs to a natural person, so both the first "
                f"name and the family name are required. Enter them {home}.",
                f"{wrapper}/Person",
                role=role,
            )
        )

    # TR-PARTY-04 (XSD ``AddressType``; ``CountryCodeCheck``).
    address = party.address
    missing = [
        label
        for label, value in (
            ("district (ilçe)", address.district),
            ("province (il)", address.city),
            ("country", address.country_name),
        )
        if not value.strip()
    ]
    if missing:
        out.append(
            _v(
                "TR-PARTY-04",
                FATAL,
                f"The {role}'s address is missing the {', '.join(missing)}. An e-Fatura address must name "
                f"the district, the province and the country. Complete it {home}.",
                f"{wrapper}/PostalAddress",
                role=role,
                missing=", ".join(missing),
            )
        )
    if address.country_code and address.country_code not in COUNTRY_CODES:
        out.append(
            _v(
                "TR-PARTY-04",
                FATAL,
                f"The {role}'s country code {address.country_code!r} is not one GİB accepts. Use the two "
                "letter ISO code, for example TR.",
                f"{wrapper}/PostalAddress/Country/IdentificationCode",
                role=role,
                country_code=address.country_code,
            )
        )

    # TR-PARTY-06 (``PartyIdentificationSchemeIDCheck``).
    for scheme, value in party.extra_ids:
        if scheme not in PARTY_ID_SCHEMES or not value.strip():
            out.append(
                _v(
                    "TR-PARTY-06",
                    FATAL,
                    f"The {role}'s additional identifier {scheme!r} is not an identifier scheme GİB accepts, "
                    "or its value is empty. Examples of valid schemes are MERSISNO and TICARETSICILNO.",
                    f"{wrapper}/PartyIdentification/ID",
                    role=role,
                    scheme=scheme,
                )
            )
    return out


def _check_parties(inv: TrInvoice) -> list[RuleViolation]:
    out = _check_party(inv.supplier, "supplier", _SUPPLIER_HOME, "AccountingSupplierParty")
    out += _check_party(inv.customer, "customer", _CUSTOMER_HOME, "AccountingCustomerParty")
    # TR-PARTY-05: ours, a warning. The Schematron demands the tax office for
    # the export scenario only, while every official sample states it for both
    # parties. Whether the customer's integrator insists on it is theirs to say.
    for party, role, home, wrapper in (
        (inv.supplier, "supplier", _SUPPLIER_HOME, "AccountingSupplierParty"),
        (inv.customer, "customer", _CUSTOMER_HOME, "AccountingCustomerParty"),
    ):
        if party.id_scheme == "VKN" and not party.tax_office.strip():
            out.append(
                _v(
                    "TR-PARTY-05",
                    WARNING,
                    f"The {role}'s tax office (vergi dairesi) is empty. The file is valid without it, but "
                    f"an invoice between taxpayers is expected to name it. Enter it {home}.",
                    f"{wrapper}/PartyTaxScheme/TaxScheme/Name",
                    role=role,
                )
            )
    return out


# ── references ───────────────────────────────────────────────────────────────


def _check_references(inv: TrInvoice) -> list[RuleViolation]:
    out: list[RuleViolation] = []
    named: list[tuple[str, TrDocumentRef]] = [("ContractDocumentReference", ref) for ref in inv.contract_references]
    named += [("DespatchDocumentReference", ref) for ref in inv.despatch_references]
    if inv.order_reference:
        named.append(("OrderReference", inv.order_reference))
    # TR-REF-01 (XSD: ID is mandatory in every reference).
    for term, ref in named:
        if not ref.id.strip():
            out.append(
                _v(
                    "TR-REF-01",
                    FATAL,
                    f"A document reference ({term}) has no number. Enter the number of the referenced "
                    "document or remove the reference.",
                    term,
                )
            )

    # TR-REF-02 (``IADEInvioceCheck``).
    if inv.invoice_type == "IADE":
        if not inv.billing_references:
            out.append(
                _v(
                    "TR-REF-02",
                    FATAL,
                    "A return invoice (IADE) must name the invoice it returns. Add the original invoice's "
                    f"16 character document ID and date {_INVOICE_HOME}.",
                    "BillingReference/InvoiceDocumentReference",
                )
            )
        for ref in inv.billing_references:
            if len(ref.id.strip()) != 16 or ref.document_type_code != "IADE":
                out.append(
                    _v(
                        "TR-REF-02",
                        FATAL,
                        f"The returned invoice reference {ref.id!r} is not usable: it must be the original "
                        "invoice's 16 character document ID, with the document type code IADE.",
                        "BillingReference/InvoiceDocumentReference",
                        reference=ref.id,
                    )
                )
    return out


# ── lines and units ──────────────────────────────────────────────────────────


def _check_lines(inv: TrInvoice) -> list[RuleViolation]:
    out: list[RuleViolation] = []
    if not inv.lines:
        return [
            _v(
                "TR-LINE-01",
                FATAL,
                "The invoice has no lines. An e-Fatura needs at least one line.",
                "InvoiceLine",
            )
        ]
    keys = {group.key for group in inv.tax_groups}
    seen: set[str] = set()
    for line in inv.lines:
        term = f"InvoiceLine[{line.line_id}]"
        # TR-LINE-01 (XSD: ID, quantity, name are mandatory).
        problems = []
        if not line.line_id.strip():
            problems.append("it has no line number")
        elif line.line_id in seen:
            problems.append("its line number is used twice")
        seen.add(line.line_id)
        if not line.name.strip():
            problems.append("it has no item name")
        if line.quantity <= 0:
            problems.append("its quantity is not positive")
        if line.tax_group not in keys:
            problems.append("it belongs to no VAT group of the invoice")
        if problems:
            out.append(
                _v(
                    "TR-LINE-01",
                    FATAL,
                    f"Line {line.line_id or '(unnumbered)'} cannot be written: {'; '.join(problems)}.",
                    term,
                    line=line.line_id,
                    problems="; ".join(problems),
                )
            )
        # TR-UNIT-01 (``GeneralUnitCodeCheck``, ``InvoicedQuantityCheck``).
        if tr_unit_code(line.unit) is None:
            out.append(
                _v(
                    "TR-UNIT-01",
                    FATAL,
                    f"Line {line.line_id} uses the unit {line.unit!r}, which has no e-Fatura unit code. "
                    "Change the unit to one of the supported ones (for example m, m2, m3, kg, t, adet, set, "
                    "hour, day, lsum).",
                    f"{term}/InvoicedQuantity/@unitCode",
                    line=line.line_id,
                    unit=line.unit,
                )
            )
    return out


def _check_payment(inv: TrInvoice) -> list[RuleViolation]:
    out: list[RuleViolation] = []
    for means in inv.payment_means:
        # TR-PAY-01 (``PaymentMeansCodeCheck``, ``GeneralChannelCodeCheck``).
        if means.code not in PAYMENT_MEANS_CODES:
            out.append(
                _v(
                    "TR-PAY-01",
                    FATAL,
                    f"The payment means code {means.code!r} is not one GİB accepts. Use a UN/EDIFACT 4461 "
                    "code, for example 42 for a payment to a bank account or 1 when it is not specified.",
                    "PaymentMeans/PaymentMeansCode",
                    code=means.code,
                )
            )
        if means.channel_code and means.channel_code not in PAYMENT_CHANNEL_CODES:
            out.append(
                _v(
                    "TR-PAY-01",
                    FATAL,
                    f"The payment channel code {means.channel_code!r} is not one GİB accepts.",
                    "PaymentMeans/PaymentChannelCode",
                    code=means.channel_code,
                )
            )
    return out


# ── tax figures ──────────────────────────────────────────────────────────────


def _check_held(inv: TrInvoice) -> list[RuleViolation]:
    """TR-HELD-01 and OCE-TR-01: what the shared calculation could not, or not safely, decide."""
    out: list[RuleViolation] = []
    for group in inv.tax_groups:
        for figure in group.taxes.figures():
            if figure.status == "held":
                out.append(
                    _v(
                        "TR-HELD-01",
                        FATAL,
                        f"The tax figure {figure.kind} of the {group.vat_rate_pct}% VAT group is not decided "
                        f"yet ({figure.reason_key or 'no reason given'}), so the invoice cannot be generated. "
                        "Resolve it in the payment taxes of this invoice.",
                        f"TaxSubtotal[{group.key}]",
                        group=group.key,
                        figure=figure.kind,
                        reason=figure.reason_key,
                    )
                )
            elif figure.status == "value" and figure.review_status == "unconfirmed":
                out.append(
                    _v(
                        "OCE-TR-01",
                        WARNING,
                        f"The tax figure {figure.kind} of the {group.vat_rate_pct}% VAT group was computed "
                        f"from a statutory rate that has not been confirmed against its source "
                        f"({figure.legal_reference or 'no reference'}). Have an accountant check it before "
                        "the invoice is sent.",
                        f"TaxSubtotal[{group.key}]",
                        group=group.key,
                        figure=figure.kind,
                        legal_reference=figure.legal_reference,
                    )
                )
    return out


def _check_groups(inv: TrInvoice) -> list[RuleViolation]:
    out: list[RuleViolation] = []
    currency = inv.currency
    if not inv.tax_groups:
        return [
            _v(
                "TR-TAX-01",
                FATAL,
                "The invoice states no VAT. An e-Fatura needs a VAT block even when the VAT is zero.",
                "TaxTotal",
            )
        ]
    seen: set[str] = set()
    for group in inv.tax_groups:
        term = f"TaxSubtotal[{group.key}]"
        computed = group.taxes.vat_computed
        problems = []
        if group.key in seen:
            problems.append("its key is used by two groups")
        seen.add(group.key)
        if computed.status == "not_applicable":
            problems.append("its VAT is marked not applicable, where a zero VAT with an exemption reason is needed")
        if computed.rate_pct is not None and computed.rate_pct != group.vat_rate_pct:
            problems.append(f"it is labelled {group.vat_rate_pct}% but was computed at {computed.rate_pct}%")
        if computed.base is not None and not _same(computed.base, group.taxable_amount, currency):
            problems.append(
                f"its taxable amount is {_fmt(group.taxable_amount, currency)} but the VAT was computed on "
                f"{_fmt(computed.base, currency)}"
            )
        if group.vat_rate_pct < 0:
            problems.append("its VAT rate is negative")
        # TR-TAX-01: ours. The group must be the calculation it claims to be.
        if problems:
            out.append(
                _v(
                    "TR-TAX-01",
                    FATAL,
                    f"The {group.vat_rate_pct}% VAT group is inconsistent: {'; '.join(problems)}.",
                    term,
                    group=group.key,
                    problems="; ".join(problems),
                )
            )
    return out


def _check_withholding(inv: TrInvoice) -> list[RuleViolation]:
    out: list[RuleViolation] = []
    currency = inv.currency
    withheld = [group for group in inv.tax_groups if has_withholding(group)]

    # TR-WH-01 (``GeneralWithholdingTaxTotalCheck``).
    if withheld and inv.invoice_type in SUPPORTED_INVOICE_TYPES and inv.invoice_type not in _WITHHOLDING_TYPES:
        out.append(
            _v(
                "TR-WH-01",
                FATAL,
                f"VAT is withheld on this invoice, which is only allowed on a TEVKIFAT invoice (or a return). "
                f"Change the invoice type from {inv.invoice_type} to TEVKIFAT, or remove the withholding.",
                "WithholdingTaxTotal",
                invoice_type=inv.invoice_type,
            )
        )
    # TR-WH-02: ours. The Schematron does not ask for the block, but a
    # TEVKIFAT invoice without one says nothing about what is withheld.
    # Silent while a withholding figure is still held: TR-HELD-01 already
    # says so, and "nothing is withheld" would be a second, wrong finding.
    undecided = any(group.taxes.vat_withheld.status == "held" for group in inv.tax_groups)
    if inv.invoice_type == "TEVKIFAT" and not withheld and not undecided:
        out.append(
            _v(
                "TR-WH-02",
                FATAL,
                "The invoice type is TEVKIFAT but no VAT is withheld on any line. Choose the withholding "
                "category in the payment taxes of this invoice, or change the type to SATIS.",
                "WithholdingTaxTotal",
            )
        )

    for group in inv.tax_groups:
        term = f"WithholdingTaxTotal/TaxSubtotal[{group.key}]"
        figure = group.taxes.vat_withheld
        if not has_withholding(group):
            # TR-WH-04: a code with no withheld amount behind it.
            if group.withholding_code and figure.status != "held":
                out.append(
                    _v(
                        "TR-WH-04",
                        FATAL,
                        f"The {group.vat_rate_pct}% VAT group names withholding code {group.withholding_code} "
                        "but no withheld VAT was computed for it.",
                        term,
                        group=group.key,
                        code=group.withholding_code,
                    )
                )
            continue

        # TR-WH-03 (``WithholdingTaxTotalCheck``).
        percent = withholding_percent(group)
        code = group.withholding_code
        if code not in WITHHOLDING_CODES:
            out.append(
                _v(
                    "TR-WH-03",
                    FATAL,
                    f"{code!r} is not a VAT withholding code GİB accepts. Choose the withholding category "
                    "from the list in the payment taxes of this invoice.",
                    term,
                    group=group.key,
                    code=code,
                )
            )
        elif (
            percent is None
            or percent != percent.to_integral_value()
            or f"{code}{int(percent)}" not in (WITHHOLDING_CODE_PERCENT_PAIRS)
        ):
            shown = "no percentage" if percent is None else f"{percent.normalize():f}%"
            out.append(
                _v(
                    "TR-WH-03",
                    FATAL,
                    f"Withholding code {code} cannot be combined with {shown}. GİB accepts each code only "
                    "with the percentage of its own withholding fraction.",
                    term,
                    group=group.key,
                    code=code,
                    percent="" if percent is None else f"{percent.normalize():f}",
                )
            )

        # TR-WH-04: ours. The block must be the calculation it claims to be.
        problems = []
        if figure.code and figure.code != code:
            problems.append(f"it is labelled {code} but was computed for code {figure.code}")
        computed = group.taxes.vat_computed.amount
        if figure.base is not None and computed is not None and not _same(figure.base, computed, currency):
            problems.append(
                f"it was computed on {_fmt(figure.base, currency)} while the VAT of the group is "
                f"{_fmt(computed, currency)}"
            )
        if figure.amount is not None and computed is not None and figure.amount > computed:
            problems.append("it withholds more than the VAT of the group")
        if problems:
            out.append(
                _v(
                    "TR-WH-04",
                    FATAL,
                    f"The withholding of the {group.vat_rate_pct}% VAT group is inconsistent: {'; '.join(problems)}.",
                    term,
                    group=group.key,
                    problems="; ".join(problems),
                )
            )
    return out


def _check_exemptions(inv: TrInvoice) -> list[RuleViolation]:
    out: list[RuleViolation] = []
    invoice_type = inv.invoice_type
    is_return = invoice_type == "IADE"
    exempt_groups = 0
    for group in inv.tax_groups:
        term = f"TaxSubtotal[{group.key}]/TaxCategory"
        code = group.exemption_reason_code.strip()
        reason = group.exemption_reason.strip()
        vat = group.taxes.vat_computed.amount if group.taxes.vat_computed.status == "value" else None
        zero_vat = vat is not None and vat == 0

        # TR-EXM-01 (``TaxExemptionReasonCheck``). A return is excused there.
        if zero_vat and not reason and not is_return:
            out.append(
                _v(
                    "TR-EXM-01",
                    FATAL,
                    f"The {group.vat_rate_pct}% VAT group charges no VAT, so it must say why: enter the "
                    f"exemption reason code and its text {_INVOICE_HOME}.",
                    term,
                    group=group.key,
                )
            )
        # TR-EXM-02 (``TaxExemptionReasonCodeCheck``, first two assertions).
        if (reason or code) and (not reason or code not in EXEMPTION_REASON_CODES):
            out.append(
                _v(
                    "TR-EXM-02",
                    FATAL,
                    f"The exemption of the {group.vat_rate_pct}% VAT group is incomplete: it needs both a "
                    f"reason text and a reason code GİB accepts, and has code {code!r}.",
                    term,
                    group=group.key,
                    code=code,
                )
            )
        # TR-EXM-03 (``TaxExemptionReasonCodeCheck``, the type assertions).
        if code in EXEMPTION_REASON_CODES and not is_return:
            if code in ISTISNA_REASON_CODES and invoice_type != "ISTISNA":
                out.append(
                    _v(
                        "TR-EXM-03",
                        FATAL,
                        f"Exemption reason code {code} is only allowed on an ISTISNA invoice, and this "
                        f"invoice is of type {invoice_type}.",
                        term,
                        group=group.key,
                        code=code,
                        invoice_type=invoice_type,
                    )
                )
            if code in _OTHER_TYPE_REASON_CODES:
                out.append(
                    _v(
                        "TR-EXM-03",
                        FATAL,
                        f"Exemption reason code {code} belongs to an invoice type that is not supported yet "
                        "(OZELMATRAH or IHRACKAYITLI).",
                        term,
                        group=group.key,
                        code=code,
                        invoice_type=invoice_type,
                    )
                )
        # TR-EXM-04 (``DemirbasKDVTaxExemptionCheck``).
        if code == _REASON_CODE_555 and (invoice_type == "ISTISNA" or zero_vat or group.vat_rate_pct == 0):
            out.append(
                _v(
                    "TR-EXM-04",
                    FATAL,
                    "Reason code 555 marks a sale outside the VAT rate check. It cannot be used on an "
                    "ISTISNA invoice, and the VAT of its group cannot be zero.",
                    term,
                    group=group.key,
                    invoice_type=invoice_type,
                )
            )
        if code in ISTISNA_REASON_CODES and code in EXEMPTION_REASON_CODES:
            exempt_groups += 1

    # TR-TYPE-02: ours. An ISTISNA invoice that exempts nothing is mistyped.
    if invoice_type == "ISTISNA" and inv.tax_groups and not exempt_groups:
        out.append(
            _v(
                "TR-TYPE-02",
                FATAL,
                "The invoice type is ISTISNA but no VAT group carries an exemption reason code. Enter the "
                "exemption, or change the type to SATIS.",
                "InvoiceTypeCode",
            )
        )
    return out


# ── sums ─────────────────────────────────────────────────────────────────────


def _check_sums(inv: TrInvoice) -> list[RuleViolation]:
    """The TR-SUM family. None of it is in the Schematron; all of it is in the official samples."""
    out: list[RuleViolation] = []
    currency = inv.currency
    totals = inv.totals
    zero = Decimal("0")

    line_allowances = sum((a.amount for ln in inv.lines for a in ln.allowances if not a.is_charge), zero)
    line_charges = sum((a.amount for ln in inv.lines for a in ln.allowances if a.is_charge), zero)
    doc_allowances = sum((a.amount for a in inv.allowance_charges if not a.is_charge), zero)
    doc_charges = sum((a.amount for a in inv.allowance_charges if a.is_charge), zero)
    allowances = line_allowances + doc_allowances
    charges = line_charges + doc_charges
    net_lines = sum((ln.line_amount for ln in inv.lines), zero)

    # TR-SUM-01. In UBL-TR a line amount is already net of the line's own
    # discount, while the document's LineExtensionAmount is the gross of all
    # lines before any discount (the official commercial sample: 26003.40
    # gross, 786.90 of line discounts, 25216.50 taxable).
    gross_lines = net_lines + line_allowances - line_charges
    if not _same(totals.line_extension, gross_lines, currency):
        out.append(
            _v(
                "TR-SUM-01",
                FATAL,
                f"The total of the lines is stated as {_fmt(totals.line_extension, currency)} but the lines "
                f"add up to {_fmt(gross_lines, currency)} before discounts.",
                "LegalMonetaryTotal/LineExtensionAmount",
                stated=_q(totals.line_extension, currency),
                expected=_q(gross_lines, currency),
            )
        )
    expected_exclusive = totals.line_extension - allowances + charges
    stated_allowance = totals.allowance_total if totals.allowance_total is not None else zero
    stated_charge = totals.charge_total if totals.charge_total is not None else zero
    if (
        not _same(totals.tax_exclusive, expected_exclusive, currency)
        or not _same(stated_allowance, allowances, currency)
        or not _same(stated_charge, charges, currency)
    ):
        out.append(
            _v(
                "TR-SUM-01",
                FATAL,
                f"The taxable total is stated as {_fmt(totals.tax_exclusive, currency)} with discounts of "
                f"{_fmt(stated_allowance, currency)} and surcharges of {_fmt(stated_charge, currency)}, but "
                f"the lines less the discounts of {_fmt(allowances, currency)} plus the surcharges of "
                f"{_fmt(charges, currency)} give {_fmt(expected_exclusive, currency)}.",
                "LegalMonetaryTotal/TaxExclusiveAmount",
                stated=_q(totals.tax_exclusive, currency),
                expected=_q(expected_exclusive, currency),
            )
        )

    # TR-SUM-04: the VAT groups together are the taxable total, and each is
    # its own lines when no document level discount moves amounts between them.
    group_base = sum((group.taxable_amount for group in inv.tax_groups), zero)
    if inv.tax_groups and not _same(group_base, totals.tax_exclusive, currency):
        out.append(
            _v(
                "TR-SUM-04",
                FATAL,
                f"The VAT groups are computed on {_fmt(group_base, currency)} in all, but the taxable total "
                f"of the invoice is {_fmt(totals.tax_exclusive, currency)}.",
                "TaxTotal/TaxSubtotal/TaxableAmount",
                stated=_q(group_base, currency),
                expected=_q(totals.tax_exclusive, currency),
            )
        )
    if not inv.allowance_charges:
        for group in inv.tax_groups:
            lines_of_group = sum((ln.line_amount for ln in inv.lines if ln.tax_group == group.key), zero)
            if not _same(lines_of_group, group.taxable_amount, currency):
                out.append(
                    _v(
                        "TR-SUM-04",
                        FATAL,
                        f"The {group.vat_rate_pct}% VAT group is computed on "
                        f"{_fmt(group.taxable_amount, currency)} but its lines add up to "
                        f"{_fmt(lines_of_group, currency)}.",
                        f"TaxSubtotal[{group.key}]/TaxableAmount",
                        group=group.key,
                        stated=_q(group.taxable_amount, currency),
                        expected=_q(lines_of_group, currency),
                    )
                )

    # TR-SUM-02: the total with tax carries the FULL computed VAT, also when
    # part of it is withheld (official samples: 20000 + 3600 = 23600 and
    # 225.00 + 22.50 = 247.50).
    computed = document_vat_computed(inv)
    if computed is not None and not _same(totals.tax_inclusive, totals.tax_exclusive + computed, currency):
        out.append(
            _v(
                "TR-SUM-02",
                FATAL,
                f"The total including tax is stated as {_fmt(totals.tax_inclusive, currency)}, but the "
                f"taxable total of {_fmt(totals.tax_exclusive, currency)} plus the computed VAT of "
                f"{_fmt(computed, currency)} is {_fmt(totals.tax_exclusive + computed, currency)}.",
                "LegalMonetaryTotal/TaxInclusiveAmount",
                stated=_q(totals.tax_inclusive, currency),
                expected=_q(totals.tax_exclusive + computed, currency),
            )
        )

    # TR-SUM-03: the amount to pay is that total less the VAT the customer
    # withholds (official samples: 23600 - 3240 = 20360 and 247.50 - 20.25 = 227.25).
    withheld = document_vat_withheld(inv)
    if withheld is not None:
        rounding = totals.payable_rounding if totals.payable_rounding is not None else zero
        # From the taxable total, not from the stated total with tax: a wrong
        # total with tax is TR-SUM-02's finding and must not be reported twice.
        inclusive = totals.tax_exclusive + computed if computed is not None else totals.tax_inclusive
        expected_payable = inclusive - withheld + rounding
        if not _same(totals.payable, expected_payable, currency):
            out.append(
                _v(
                    "TR-SUM-03",
                    FATAL,
                    f"The amount to pay is stated as {_fmt(totals.payable, currency)}, but the total "
                    f"including tax of {_fmt(inclusive, currency)} less the withheld VAT of "
                    f"{_fmt(withheld, currency)} is {_fmt(expected_payable, currency)}.",
                    "LegalMonetaryTotal/PayableAmount",
                    stated=_q(totals.payable, currency),
                    expected=_q(expected_payable, currency),
                )
            )

    for group in inv.tax_groups:
        out += _check_group_sums(inv, group)
    return out


def _check_group_sums(inv: TrInvoice, group: TrTaxGroup) -> list[RuleViolation]:
    out: list[RuleViolation] = []
    currency = inv.currency
    zero = Decimal("0")
    taxes = group.taxes
    if taxes.vat_computed.status != "value" or taxes.vat_payable.status != "value":
        return out
    if taxes.vat_withheld.status == "held":
        return out
    computed = taxes.vat_computed.amount or zero
    payable = taxes.vat_payable.amount or zero
    withheld = (taxes.vat_withheld.amount or zero) if has_withholding(group) else zero

    # TR-SUM-05: computed, withheld and payable VAT of a group close exactly.
    if not _same(payable, computed - withheld, currency):
        out.append(
            _v(
                "TR-SUM-05",
                FATAL,
                f"The VAT of the {group.vat_rate_pct}% group does not close: computed "
                f"{_fmt(computed, currency)} less withheld {_fmt(withheld, currency)} is not the payable VAT "
                f"of {_fmt(payable, currency)}.",
                f"TaxSubtotal[{group.key}]/TaxAmount",
                group=group.key,
                computed=_q(computed, currency),
                withheld=_q(withheld, currency),
                payable=_q(payable, currency),
            )
        )

    # TR-SUM-06: the lines of a group carry its figures, all of them or none.
    lines = [ln for ln in inv.lines if ln.tax_group == group.key]
    with_tax = [ln for ln in lines if ln.vat_amount is not None]
    if not with_tax:
        return out
    term = f"TaxSubtotal[{group.key}]"
    if len(with_tax) != len(lines):
        out.append(
            _v(
                "TR-SUM-06",
                FATAL,
                f"Some lines of the {group.vat_rate_pct}% VAT group state their VAT and others do not. "
                "Either every line of a group carries its share or none does.",
                term,
                group=group.key,
            )
        )
        return out
    line_computed = sum((ln.vat_amount or zero for ln in lines), zero)
    line_withheld = sum((ln.vat_withheld or zero for ln in lines), zero)
    open_lines = [
        ln.line_id
        for ln in lines
        if ln.vat_payable is None
        or not _same(ln.vat_payable, (ln.vat_amount or zero) - (ln.vat_withheld or zero), currency)
    ]
    if not _same(line_computed, computed, currency) or not _same(line_withheld, withheld, currency) or open_lines:
        detail = f" Lines that do not close: {', '.join(open_lines)}." if open_lines else ""
        out.append(
            _v(
                "TR-SUM-06",
                FATAL,
                f"The lines of the {group.vat_rate_pct}% VAT group carry {_fmt(line_computed, currency)} of "
                f"VAT and {_fmt(line_withheld, currency)} of withheld VAT, while the group itself has "
                f"{_fmt(computed, currency)} and {_fmt(withheld, currency)}.{detail}",
                term,
                group=group.key,
                line_computed=_q(line_computed, currency),
                line_withheld=_q(line_withheld, currency),
                computed=_q(computed, currency),
                withheld=_q(withheld, currency),
            )
        )
    return out


# ── entry point ──────────────────────────────────────────────────────────────


def check_tr(inv: TrInvoice, *, today: dt.date | None = None) -> list[RuleViolation]:
    """Check a UBL-TR invoice and report everything that is wrong with it.

    Args:
        inv: the invoice.
        today: the day to judge the issue date against. Defaults to the
            calendar day in Türkiye; tests pass a fixed day.

    Returns:
        Every finding, fatal ones and warnings, in a stable order. An empty
        list means the document can be generated and handed to the integrator.
    """
    day = today or today_in_turkiye()
    out = _check_header(inv, day)
    out += _check_currency(inv)
    out += _check_parties(inv)
    out += _check_references(inv)
    out += _check_lines(inv)
    out += _check_payment(inv)
    out += _check_held(inv)
    out += _check_groups(inv)
    out += _check_withholding(inv)
    out += _check_exemptions(inv)
    # Sums over amounts that are negative or unknown say nothing useful, and
    # the findings above already explain why.
    out += _check_amounts(inv)
    out += _check_sums(inv)
    return out
