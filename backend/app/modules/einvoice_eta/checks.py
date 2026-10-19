# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What ETA will refuse, found before the document leaves.

Pure functions over the document text. The validation rules in
:mod:`app.modules.einvoice_eta.validators` group these findings and report
them; nothing here touches a session or the network.

Each check names the ETA page it mirrors. A check that rests on a fact ETA does
not publish (the person receiver threshold, the EGS code format) is advisory
and never blocks, as the Egypt brief requires for unconfirmed facts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.modules.einvoice_eta.calculation import check_document
from app.modules.einvoice_eta.codes import (
    DOCUMENT_TYPE_VERSION,
    DOCUMENT_TYPES,
    EGP,
    EGS_CODE_PREFIX,
    EXPORT_TYPES,
    FIXED_AMOUNT_TYPES,
    ITEM_TYPES,
    PARTY_BUSINESS,
    PARTY_FOREIGNER,
    PARTY_PERSON,
    PARTY_TYPES,
    REFERENCING_TYPES,
    activity_codes,
    person_id_threshold,
    tax_subtypes,
    tax_types,
    unit_types,
)

GROUP_READABLE = "readable"
GROUP_PARTIES = "parties"
GROUP_HEADER = "header"
GROUP_LINES = "lines"
GROUP_TOTALS = "totals"
GROUP_ADVISORY = "advisory"

GROUPS: tuple[str, ...] = (
    GROUP_READABLE,
    GROUP_PARTIES,
    GROUP_HEADER,
    GROUP_LINES,
    GROUP_TOTALS,
    GROUP_ADVISORY,
)

# Address members ETA does not mark optional.
_REQUIRED_ADDRESS = ("country", "governate", "regionCity", "street", "buildingNumber")


@dataclass(frozen=True)
class EtaIssue:
    """One thing ETA would refuse, or that a reader should look at."""

    group: str
    code: str
    path: str
    message: str


def _get(obj: Any, *names: str) -> Any:
    """A member by any of its spellings; ETA's pages and samples differ in case."""
    if not isinstance(obj, dict):
        return None
    for name in names:
        if name in obj:
            return obj[name]
    lowered = {str(k).lower(): v for k, v in obj.items()}
    for name in names:
        if name.lower() in lowered:
            return lowered[name.lower()]
    return None


def _text(value: Any) -> str:
    return str(value).strip() if value is not None and not isinstance(value, (dict, list)) else ""


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, (bool, dict, list)):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_document(text: str) -> tuple[dict[str, Any] | None, str]:
    """Parse the payload with exact decimals. Returns ``(doc, error)``."""
    try:
        doc = json.loads((text or "").lstrip("﻿"), parse_float=Decimal, parse_int=Decimal)
    except json.JSONDecodeError as exc:
        return None, f"The document is not valid JSON ({exc.msg}, line {exc.lineno})."
    if not isinstance(doc, dict):
        return None, "The document must be one JSON object."
    return doc, ""


def _check_address(issues: list[EtaIssue], who: str, address: Any) -> None:
    if not isinstance(address, dict):
        issues.append(EtaIssue(GROUP_PARTIES, f"{who}_address_missing", f"{who}.address", f"The {who} has no address."))
        return
    missing = [name for name in _REQUIRED_ADDRESS if not _text(_get(address, name))]
    if missing:
        issues.append(
            EtaIssue(
                GROUP_PARTIES,
                f"{who}_address_incomplete",
                f"{who}.address",
                f"The {who} address is missing {', '.join(missing)}.",
            )
        )


def _rin_checker() -> Any:
    """The shared party identifier check, or ``None`` where it is not installed.

    The RIN format belongs to ``app.core.party_identifiers`` (scheme ``rin`` for
    EG), not to this module, so the rule is written once for every caller.
    """
    try:
        from app.core.party_identifiers import check
    except ImportError:
        return None
    return check


_RIN_REASONS = {
    "empty": "it is empty",
    "format": "an Egyptian RIN is 9 digits",
}


def _field(result: Any, name: str) -> Any:
    return result.get(name) if isinstance(result, dict) else getattr(result, name, None)


def _rin_verdict(value: str) -> tuple[bool | None, str, bool]:
    """``(valid, why, firm)``; ``valid`` is ``None`` when nothing checked it.

    ``firm`` is False when the shared check marks its own rule for expert review:
    an unconfirmed rule warns and does not block.
    """
    check = _rin_checker()
    result = check("EG", "rin", value) if check is not None else None
    if result is None:
        return None, "", False
    valid = _field(result, "valid")
    if valid is None:
        return None, "", False
    reason = str(_field(result, "reason") or "")
    why = _RIN_REASONS.get(reason, reason)
    details = _field(result, "details")
    review = details.get("needs_expert_review") if isinstance(details, dict) else None
    firm = str(review).strip().lower() not in ("yes", "true", "1")
    return bool(valid), why, firm


def _check_rin(issues: list[EtaIssue], who: str, value: str, unchecked: list[str]) -> None:
    valid, why, firm = _rin_verdict(value)
    if valid is None:
        unchecked.append(f"{who}.id")
    elif not valid:
        message = f"The {who} tax registration number {value} is not a valid Egyptian RIN" + (
            f": {why}." if why else "."
        )
        if not firm:
            message += " The format rule is awaiting expert review, so this is a warning."
        issues.append(EtaIssue(GROUP_PARTIES if firm else GROUP_ADVISORY, f"{who}_rin_invalid", f"{who}.id", message))


def _check_parties(issues: list[EtaIssue], doc: dict[str, Any], profile_rin: str) -> None:
    unchecked: list[str] = []
    _check_parties_inner(issues, doc, profile_rin, unchecked)
    if unchecked:
        issues.append(
            EtaIssue(
                GROUP_ADVISORY,
                "rin_format_unchecked",
                ", ".join(unchecked),
                "The format of the tax registration number was not checked: no Egyptian RIN check is installed.",
            )
        )


def _check_parties_inner(issues: list[EtaIssue], doc: dict[str, Any], profile_rin: str, unchecked: list[str]) -> None:
    issuer = _get(doc, "issuer")
    if not isinstance(issuer, dict):
        issues.append(EtaIssue(GROUP_PARTIES, "issuer_missing", "issuer", "The document names no issuer."))
        issuer = {}
    else:
        issuer_type = _text(_get(issuer, "type")).upper()
        if issuer_type != PARTY_BUSINESS:
            issues.append(
                EtaIssue(
                    GROUP_PARTIES,
                    "issuer_type",
                    "issuer.type",
                    f"The issuer type is {issuer_type or 'empty'}; ETA accepts B (a business registered in Egypt) "
                    "for the issuer, the other types are reserved.",
                )
            )
        issuer_id = _text(_get(issuer, "id"))
        if not issuer_id:
            issues.append(
                EtaIssue(
                    GROUP_PARTIES,
                    "issuer_rin_missing",
                    "issuer.id",
                    "The issuer has no tax registration number (RIN).",
                )
            )
        else:
            _check_rin(issues, "issuer", issuer_id, unchecked)
        if issuer_id and profile_rin and issuer_id != profile_rin.strip():
            issues.append(
                EtaIssue(
                    GROUP_PARTIES,
                    "issuer_rin_mismatch",
                    "issuer.id",
                    f"The issuer RIN on the document is {issuer_id} but the registration is for {profile_rin.strip()}. "
                    "ETA refuses a document submitted for another taxpayer.",
                )
            )
        if not _text(_get(issuer, "name")):
            issues.append(EtaIssue(GROUP_PARTIES, "issuer_name_missing", "issuer.name", "The issuer has no name."))
        address = _get(issuer, "address")
        _check_address(issues, "issuer", address)
        if isinstance(address, dict):
            if not _text(_get(address, "branchID", "branchId")):
                issues.append(
                    EtaIssue(
                        GROUP_PARTIES,
                        "issuer_branch_missing",
                        "issuer.address.branchID",
                        "A business issuer needs the branch code it registered with ETA (branchID; 0 for the main "
                        "branch is a common registration).",
                    )
                )
            country = _text(_get(address, "country")).upper()
            if country and country != "EG":
                issues.append(
                    EtaIssue(
                        GROUP_PARTIES,
                        "issuer_country",
                        "issuer.address.country",
                        f"An Egyptian business issuer must have country EG, not {country}.",
                    )
                )

    receiver = _get(doc, "receiver")
    if not isinstance(receiver, dict):
        issues.append(EtaIssue(GROUP_PARTIES, "receiver_missing", "receiver", "The document names no receiver."))
        return
    receiver_type = _text(_get(receiver, "type")).upper()
    receiver_id = _text(_get(receiver, "id"))
    if receiver_type not in PARTY_TYPES:
        issues.append(
            EtaIssue(
                GROUP_PARTIES,
                "receiver_type",
                "receiver.type",
                f"The receiver type is {receiver_type or 'empty'}; it must be B (business in Egypt), P (natural "
                "person) or F (foreigner).",
            )
        )
        return
    if receiver_type in (PARTY_BUSINESS, PARTY_FOREIGNER):
        if not receiver_id:
            what = "tax registration number" if receiver_type == PARTY_BUSINESS else "foreign VAT id"
            issues.append(EtaIssue(GROUP_PARTIES, "receiver_id_missing", "receiver.id", f"The receiver has no {what}."))
        elif receiver_type == PARTY_BUSINESS:
            _check_rin(issues, "receiver", receiver_id, unchecked)
        if not _text(_get(receiver, "name")):
            issues.append(
                EtaIssue(GROUP_PARTIES, "receiver_name_missing", "receiver.name", "The receiver has no name.")
            )
        address = _get(receiver, "address")
        _check_address(issues, "receiver", address)
        country = _text(_get(address, "country")).upper() if isinstance(address, dict) else ""
        if receiver_type == PARTY_FOREIGNER and country == "EG":
            issues.append(
                EtaIssue(
                    GROUP_PARTIES,
                    "receiver_foreign_country",
                    "receiver.address.country",
                    "A foreign receiver (type F) cannot have country EG.",
                )
            )
        if receiver_type == PARTY_BUSINESS and country and country != "EG":
            issues.append(
                EtaIssue(
                    GROUP_PARTIES,
                    "receiver_business_country",
                    "receiver.address.country",
                    f"A business receiver (type B) is registered in Egypt; country {country} means type F.",
                )
            )
    issuer_id = _text(_get(issuer, "id"))
    if receiver_id and issuer_id and receiver_id == issuer_id:
        issues.append(
            EtaIssue(
                GROUP_PARTIES,
                "receiver_is_issuer",
                "receiver.id",
                "The receiver and the issuer are the same taxpayer; ETA refuses a document issued to oneself.",
            )
        )


def _check_header(issues: list[EtaIssue], doc: dict[str, Any], now: datetime) -> str:
    doc_type = _text(_get(doc, "documentType")).lower()
    if doc_type not in DOCUMENT_TYPES:
        issues.append(
            EtaIssue(
                GROUP_HEADER,
                "document_type",
                "documentType",
                f"The document type is {doc_type or 'empty'}; ETA accepts {', '.join(DOCUMENT_TYPES)}.",
            )
        )
    version = _text(_get(doc, "documentTypeVersion"))
    if version != DOCUMENT_TYPE_VERSION:
        issues.append(
            EtaIssue(
                GROUP_HEADER,
                "document_version",
                "documentTypeVersion",
                f"The document type version is {version or 'empty'}; signed documents use {DOCUMENT_TYPE_VERSION}.",
            )
        )
    issued_raw = _text(_get(doc, "dateTimeIssued"))
    if not issued_raw:
        issues.append(EtaIssue(GROUP_HEADER, "issued_missing", "dateTimeIssued", "The issue date and time is missing."))
    else:
        try:
            issued = datetime.fromisoformat(issued_raw.replace("Z", "+00:00"))
        except ValueError:
            issued = None
        if issued is None or not issued_raw.endswith("Z") or issued.tzinfo is None:
            issues.append(
                EtaIssue(
                    GROUP_HEADER,
                    "issued_not_utc",
                    "dateTimeIssued",
                    f"The issue date and time {issued_raw} must be UTC in the form 2026-10-19T08:30:00Z.",
                )
            )
        elif issued > now:
            issues.append(
                EtaIssue(
                    GROUP_HEADER,
                    "issued_in_future",
                    "dateTimeIssued",
                    f"The issue date and time {issued_raw} is in the future; ETA refuses it.",
                )
            )
    activity = _text(_get(doc, "taxpayerActivityCode"))
    if not activity:
        issues.append(
            EtaIssue(
                GROUP_HEADER,
                "activity_code_missing",
                "taxpayerActivityCode",
                "The taxpayer activity code is missing (for example 4100 for building construction).",
            )
        )
    elif activity not in activity_codes():
        issues.append(
            EtaIssue(
                GROUP_HEADER,
                "activity_code_unknown",
                "taxpayerActivityCode",
                f"The activity code {activity} is not in ETA's activity code table.",
            )
        )
    if not _text(_get(doc, "internalID", "internalId")):
        issues.append(
            EtaIssue(
                GROUP_HEADER,
                "internal_id_missing",
                "internalID",
                "The internal document id (the ERP invoice number) is missing.",
            )
        )
    lines = _get(doc, "invoiceLines")
    if not isinstance(lines, list) or not lines:
        issues.append(EtaIssue(GROUP_HEADER, "no_lines", "invoiceLines", "The document has no invoice lines."))
    return doc_type


def _check_lines(issues: list[EtaIssue], doc: dict[str, Any]) -> None:
    lines = _get(doc, "invoiceLines")
    if not isinstance(lines, list):
        return
    known_types = tax_types()
    parents = tax_subtypes()
    units = unit_types()
    for index, line in enumerate(lines):
        path = f"invoiceLines[{index}]"
        if not isinstance(line, dict):
            issues.append(EtaIssue(GROUP_LINES, "line_not_object", path, f"Line {index + 1} is not an object."))
            continue
        label = f"Line {index + 1}"
        if not _text(_get(line, "description")):
            issues.append(
                EtaIssue(GROUP_LINES, "description_missing", f"{path}.description", f"{label} has no description.")
            )
        item_type = _text(_get(line, "itemType")).upper()
        if item_type not in ITEM_TYPES:
            issues.append(
                EtaIssue(
                    GROUP_LINES,
                    "item_type",
                    f"{path}.itemType",
                    f"{label} uses item code type {item_type or 'empty'}; ETA v1.0 accepts GS1 or EGS.",
                )
            )
        item_code = _text(_get(line, "itemCode"))
        if not item_code:
            issues.append(
                EtaIssue(
                    GROUP_LINES,
                    "item_code_missing",
                    f"{path}.itemCode",
                    f"{label} has no item code. Register an EGS code for the service with ETA, or use the GS1 code.",
                )
            )
        elif item_type == "EGS" and not item_code.upper().startswith(EGS_CODE_PREFIX):
            issues.append(
                EtaIssue(
                    GROUP_ADVISORY,
                    "egs_code_prefix",
                    f"{path}.itemCode",
                    f"{label}: the EGS code {item_code} does not start with {EGS_CODE_PREFIX}. EGS codes are issued "
                    "as EG- followed by the taxpayer's RIN and its own code; check the code registered with ETA.",
                )
            )
        unit = _text(_get(line, "unitType"))
        if unit not in units:
            issues.append(
                EtaIssue(
                    GROUP_LINES,
                    "unit_type",
                    f"{path}.unitType",
                    f"{label} uses unit {unit or 'empty'}, which is not in ETA's unit table (square metre is MTK, "
                    "cubic metre MTQ, kilogram KGM).",
                )
            )
        quantity = _dec(_get(line, "quantity"))
        if quantity is None or quantity <= 0:
            issues.append(
                EtaIssue(GROUP_LINES, "quantity", f"{path}.quantity", f"{label} needs a quantity greater than 0.")
            )
        value = _get(line, "unitValue")
        if not isinstance(value, dict):
            issues.append(
                EtaIssue(GROUP_LINES, "unit_value_missing", f"{path}.unitValue", f"{label} has no unit price.")
            )
        else:
            currency = _text(_get(value, "currencySold")).upper()
            if len(currency) != 3:
                issues.append(
                    EtaIssue(
                        GROUP_LINES,
                        "currency",
                        f"{path}.unitValue.currencySold",
                        f"{label} needs the ISO 4217 currency it was sold in.",
                    )
                )
            if _dec(_get(value, "amountEGP")) is None:
                issues.append(
                    EtaIssue(
                        GROUP_LINES, "amount_egp", f"{path}.unitValue.amountEGP", f"{label} has no unit price in EGP."
                    )
                )
            sold = _dec(_get(value, "amountSold"))
            rate = _dec(_get(value, "currencyExchangeRate"))
            if currency and currency != EGP:
                if sold is None or rate is None or rate <= 0:
                    issues.append(
                        EtaIssue(
                            GROUP_LINES,
                            "foreign_currency",
                            f"{path}.unitValue",
                            f"{label} is sold in {currency}, so it needs amountSold and the exchange rate to EGP.",
                        )
                    )
            elif currency == EGP and sold is not None and sold != 0:
                issues.append(
                    EtaIssue(
                        GROUP_LINES,
                        "egp_amount_sold",
                        f"{path}.unitValue.amountSold",
                        f"{label} is sold in EGP, so amountSold must be left out.",
                    )
                )
        discount = _get(line, "discount")
        if isinstance(discount, dict):
            discount_rate = _dec(_get(discount, "rate"))
            if discount_rate is not None and not (0 <= discount_rate <= 100):
                issues.append(
                    EtaIssue(
                        GROUP_LINES,
                        "discount_rate",
                        f"{path}.discount.rate",
                        f"{label} has a discount rate of {discount_rate}; it must be between 0 and 100.",
                    )
                )
        items = _get(line, "taxableItems")
        if items is None:
            continue
        if not isinstance(items, list):
            issues.append(
                EtaIssue(GROUP_LINES, "taxable_items", f"{path}.taxableItems", f"{label} taxes are not a list.")
            )
            continue
        seen: set[str] = set()
        for position, item in enumerate(items):
            item_path = f"{path}.taxableItems[{position}]"
            if not isinstance(item, dict):
                continue
            tax_type = _text(_get(item, "taxType")).upper()
            sub_type = _text(_get(item, "subType"))
            if tax_type not in known_types:
                issues.append(
                    EtaIssue(
                        GROUP_LINES,
                        "tax_type_unknown",
                        f"{item_path}.taxType",
                        f"{label} uses tax type {tax_type or 'empty'}, which ETA does not know (T1-T20).",
                    )
                )
                continue
            if tax_type in seen:
                issues.append(
                    EtaIssue(
                        GROUP_LINES,
                        "tax_type_twice",
                        f"{item_path}.taxType",
                        f"{label} carries {tax_type} twice; each tax type may appear once per line.",
                    )
                )
            seen.add(tax_type)
            if not sub_type:
                issues.append(
                    EtaIssue(
                        GROUP_LINES,
                        "tax_subtype_missing",
                        f"{item_path}.subType",
                        f"{label} gives no subtype for {tax_type} (for VAT on a standard rated sale, V009).",
                    )
                )
            elif parents.get(sub_type) != tax_type:
                parent = parents.get(sub_type)
                why = f"belongs to {parent}, not to {tax_type}" if parent else "is not in ETA's subtype table"
                issues.append(
                    EtaIssue(
                        GROUP_LINES,
                        "tax_subtype_parent",
                        f"{item_path}.subType",
                        f"{label}: subtype {sub_type} {why}.",
                    )
                )
            rate = _dec(_get(item, "rate"))
            if rate is not None and not (0 <= rate <= 999):
                issues.append(
                    EtaIssue(
                        GROUP_LINES,
                        "tax_rate_range",
                        f"{item_path}.rate",
                        f"{label}: the {tax_type} rate {rate} is outside 0-999.",
                    )
                )
            if tax_type in FIXED_AMOUNT_TYPES and rate not in (None, Decimal(0)):
                issues.append(
                    EtaIssue(
                        GROUP_LINES,
                        "fixed_amount_rate",
                        f"{item_path}.rate",
                        f"{label}: {tax_type} is a fixed amount, so its rate must be 0.",
                    )
                )


def _walk_strings(value: Any, path: str, out: list[tuple[str, str]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _walk_strings(child, f"{path}.{key}" if path else str(key), out)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_strings(child, f"{path}[{index}]", out)
    elif isinstance(value, str):
        out.append((path, value))


def _walk_numbers(value: Any, path: str, out: list[tuple[str, Decimal]]) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            _walk_numbers(child, f"{path}.{key}" if path else str(key), out)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _walk_numbers(child, f"{path}[{index}]", out)
    elif isinstance(value, Decimal):
        out.append((path, value))


def _check_person_threshold(issues: list[EtaIssue], doc: dict[str, Any]) -> None:
    """A natural-person receiver without national ID, against the threshold of the issue date."""
    threshold = person_id_threshold(_text(_get(doc, "dateTimeIssued")))
    total = _dec(_get(doc, "totalAmount"))
    if threshold is None or total is None:
        issues.append(
            EtaIssue(
                GROUP_ADVISORY,
                "person_without_id",
                "receiver.id",
                "The receiver is a natural person with no national ID. ETA requires it from an invoice total it "
                "sets; check before sending a large invoice.",
            )
        )
        return
    if total < threshold.amount:
        return
    issues.append(
        EtaIssue(
            GROUP_ADVISORY,
            "person_without_id",
            "receiver.id",
            f"The receiver is a natural person with no national ID, and the total {total} {threshold.currency} reaches "
            f"the {threshold.amount} {threshold.currency} from which ETA asks for it on this issue date "
            f"({threshold.source_url}, read {threshold.read_date}; figure to be confirmed).",
        )
    )


def _check_advisory(issues: list[EtaIssue], doc: dict[str, Any], doc_type: str) -> None:
    receiver = _get(doc, "receiver")
    if isinstance(receiver, dict):
        receiver_type = _text(_get(receiver, "type")).upper()
        if receiver_type == PARTY_PERSON and not _text(_get(receiver, "id")):
            _check_person_threshold(issues, doc)
        if doc_type in EXPORT_TYPES and receiver_type != PARTY_FOREIGNER:
            issues.append(
                EtaIssue(
                    GROUP_ADVISORY,
                    "export_receiver",
                    "receiver.type",
                    "An export document is normally issued to a foreign receiver (type F).",
                )
            )
    if doc_type in REFERENCING_TYPES:
        references = _get(doc, "references")
        if not isinstance(references, list) or not [r for r in references if _text(r)]:
            issues.append(
                EtaIssue(
                    GROUP_ADVISORY,
                    "no_references",
                    "references",
                    "This credit or debit note names no original invoice UUID, so ETA cannot check it against the "
                    "invoice it corrects.",
                )
            )
    strings: list[tuple[str, str]] = []
    _walk_strings(doc, "", strings)
    for path, value in strings:
        if '"' in value or "\\" in value:
            issues.append(
                EtaIssue(
                    GROUP_ADVISORY,
                    "quote_in_text",
                    path,
                    f"{path} contains a double quote or backslash. ETA does not define how these are signed; "
                    "replace them to be safe.",
                )
            )
    numbers: list[tuple[str, Decimal]] = []
    _walk_numbers(doc, "", numbers)
    for path, number in numbers:
        exponent = number.as_tuple().exponent
        if isinstance(exponent, int) and exponent < -5:
            issues.append(
                EtaIssue(
                    GROUP_ADVISORY,
                    "too_many_decimals",
                    path,
                    f"{path} has more than 5 decimals ({number}); ETA accepts 5.",
                )
            )


def check_eta_document(
    text: str,
    *,
    profile_rin: str = "",
    now: datetime | None = None,
) -> list[EtaIssue]:
    """Every finding about one ETA document, grouped.

    Args:
        text: the payload as stored.
        profile_rin: the registration's tax registration number; the issuer on
            the document must be this taxpayer.
        now: the reference time for "not in the future", UTC.
    """
    doc, error = parse_document(text)
    if doc is None:
        return [EtaIssue(GROUP_READABLE, "unreadable", "", error)]
    issues: list[EtaIssue] = []
    _check_parties(issues, doc, profile_rin)
    doc_type = _check_header(issues, doc, now or datetime.now(UTC))
    _check_lines(issues, doc)
    for broken in check_document(doc):
        issues.append(EtaIssue(GROUP_TOTALS, "equation", f"{broken.path}.{broken.field}", broken.message()))
    _check_advisory(issues, doc, doc_type)
    return issues


__all__ = [
    "GROUPS",
    "GROUP_ADVISORY",
    "GROUP_HEADER",
    "GROUP_LINES",
    "GROUP_PARTIES",
    "GROUP_READABLE",
    "GROUP_TOTALS",
    "EtaIssue",
    "check_eta_document",
    "parse_document",
]
