# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""ETA code tables and the small vocabularies of the v1.0 document.

The five JSON files in ``data/`` are the files the ETA SDK publishes, copied
unedited. They are not retyped, because a retyped code table is a second
source of truth that drifts from the authority's without anyone noticing. ETA's
own spelling is kept, including ``Desc_en`` of T9 and T17 reading "Table tax
(percentage)" where the Arabic says service charge: the codes are what ETA
validates, and the descriptions are shown as ETA wrote them.

Two mappings here are ours and not ETA's, and each says so with
``needs_expert_review``: the platform's unit spellings to ETA unit codes, and
the platform's VAT categories to ETA VAT subtypes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from decimal import Decimal
from functools import cache
from pathlib import Path
from typing import Any

_DATA = Path(__file__).resolve().parent / "data"

SDK_URL = "https://sdk.invoicing.eta.gov.eg/"
CODES_READ_DATE = "2026-10-19"

# Where each shipped table came from. Travels with the data so a reader can
# recheck it against the authority.
CODE_TABLE_SOURCES: dict[str, str] = {
    "TaxTypes.json": "https://sdk.invoicing.eta.gov.eg/files/TaxTypes.json",
    "NonTaxableTaxTypes.json": "https://sdk.invoicing.eta.gov.eg/files/NonTaxableTaxTypes.json",
    "TaxSubtypes.json": "https://sdk.invoicing.eta.gov.eg/files/TaxSubtypes.json",
    "UnitTypes.json": "https://sdk.invoicing.eta.gov.eg/files/UnitTypes.json",
    "ActivityCodes.json": "https://sdk.invoicing.eta.gov.eg/files/ActivityCodes.json",
}

# The submission's document type names, as Get Submission lists them
# (https://sdk.invoicing.eta.gov.eg/einvoicingapi/09-get-submission/). ``ii``
# (import invoice) exists on ETA's side and is not built here.
DOC_INVOICE = "i"
DOC_CREDIT_NOTE = "c"
DOC_DEBIT_NOTE = "d"
DOC_EXPORT_INVOICE = "ei"
DOC_EXPORT_CREDIT_NOTE = "ec"
DOC_EXPORT_DEBIT_NOTE = "ed"

DOCUMENT_TYPES: tuple[str, ...] = (
    DOC_INVOICE,
    DOC_CREDIT_NOTE,
    DOC_DEBIT_NOTE,
    DOC_EXPORT_INVOICE,
    DOC_EXPORT_CREDIT_NOTE,
    DOC_EXPORT_DEBIT_NOTE,
)
# Documents that amend earlier invoices and therefore point at them.
REFERENCING_TYPES: frozenset[str] = frozenset(
    {DOC_CREDIT_NOTE, DOC_DEBIT_NOTE, DOC_EXPORT_CREDIT_NOTE, DOC_EXPORT_DEBIT_NOTE}
)
EXPORT_TYPES: frozenset[str] = frozenset({DOC_EXPORT_INVOICE, DOC_EXPORT_CREDIT_NOTE, DOC_EXPORT_DEBIT_NOTE})

DOCUMENT_TYPE_VERSION = "1.0"

# Issuer and receiver types (https://sdk.invoicing.eta.gov.eg/documents/invoice-v1-0/).
PARTY_BUSINESS = "B"
PARTY_PERSON = "P"
PARTY_FOREIGNER = "F"
PARTY_TYPES: tuple[str, ...] = (PARTY_BUSINESS, PARTY_PERSON, PARTY_FOREIGNER)

# Coding schemes an invoice line may use in v1.0.
ITEM_TYPES: tuple[str, ...] = ("GS1", "EGS")

EGP = "EGP"

# Tax type groups, from the calculation rules
# (https://sdk.invoicing.eta.gov.eg/document-validation-rules/).
TAX_VAT = "T1"
TAX_TABLE_PERCENT = "T2"
TAX_TABLE_FIXED = "T3"
TAX_WITHHOLDING = "T4"
TAXABLE_FEES: tuple[str, ...] = tuple(f"T{n}" for n in range(5, 13))
NON_TAXABLE_FEES: tuple[str, ...] = tuple(f"T{n}" for n in range(13, 21))
# Fixed amount items: the rate must be zero.
FIXED_AMOUNT_TYPES: frozenset[str] = frozenset({"T3", "T6"})

# Subtypes whose amount is a fixed sum rather than a rate times the net total.
# ETA marks them "(amount)" or "(Fixed Amount)" in TaxSubtypes.json; derived from
# that file rather than listed, see ``fixed_amount_subtypes``.


@cache
def _load(name: str) -> list[dict[str, Any]]:
    with (_DATA / name).open(encoding="utf-8-sig") as handle:
        rows = json.load(handle)
    if not isinstance(rows, list):
        raise ValueError(f"{name} is not a list")
    return rows


def _code(row: dict[str, Any]) -> str:
    return str(row.get("Code") or row.get("code") or "").strip()


@cache
def tax_types() -> dict[str, str]:
    """Every tax type ETA accepts, T1-T20, with ETA's English description."""
    rows = [*_load("TaxTypes.json"), *_load("NonTaxableTaxTypes.json")]
    return {_code(r): str(r.get("Desc_en") or "") for r in rows}


@cache
def tax_subtypes() -> dict[str, str]:
    """Every subtype code mapped to its parent tax type (``W001`` -> ``T4``)."""
    return {_code(r): str(r.get("TaxtypeReference") or "").strip() for r in _load("TaxSubtypes.json")}


@cache
def tax_subtype_descriptions() -> dict[str, str]:
    """Every subtype code with ETA's English description."""
    return {_code(r): str(r.get("Desc_en") or "") for r in _load("TaxSubtypes.json")}


@cache
def fixed_amount_subtypes() -> frozenset[str]:
    """Subtypes ETA describes as an amount rather than a rate."""
    out = set()
    for code, desc in tax_subtype_descriptions().items():
        lowered = desc.lower()
        if "(amount)" in lowered or "(fixed amount)" in lowered:
            out.add(code)
    return frozenset(out)


@cache
def unit_types() -> dict[str, str]:
    """ETA unit codes with their English description."""
    return {_code(r): str(r.get("desc_en") or r.get("Desc_en") or "") for r in _load("UnitTypes.json")}


@cache
def activity_codes() -> dict[str, str]:
    """ETA taxpayer activity codes (ISIC based) with their English description."""
    return {_code(r): str(r.get("Desc_en") or r.get("desc_en") or "") for r in _load("ActivityCodes.json")}


def subtype_belongs_to(sub_type: str, tax_type: str) -> bool:
    """Whether ``sub_type`` is a child of ``tax_type`` in ETA's table."""
    return tax_subtypes().get((sub_type or "").strip()) == (tax_type or "").strip()


@dataclass(frozen=True)
class AmountThreshold:
    """An amount in force between two dates, with where it was read."""

    amount: Decimal
    currency: str
    effective_from: str  # ISO date, "" for "since before records here"
    effective_to: str  # ISO date, exclusive; "" while in force
    source_url: str
    read_date: str
    needs_expert_review: bool
    note: str


# The invoice total from which a natural-person receiver must be identified by
# national ID. The SDK says only "threshold limit defined"; the figures come from
# the head of ETA as quoted in the press (no decree text reached), so they drive a
# warning, never a refusal.
PERSON_ID_THRESHOLDS: tuple[AmountThreshold, ...] = (
    AmountThreshold(
        amount=Decimal("50000"),
        currency=EGP,
        effective_from="",
        effective_to="2024-08-01",
        source_url="https://hapijournal.com/2024/05/07/",
        read_date="2026-10-19",
        needs_expert_review=True,
        note="The earlier figure, replaced from 2024-08-01.",
    ),
    AmountThreshold(
        amount=Decimal("25000"),
        currency=EGP,
        effective_from="2024-08-01",
        effective_to="",
        source_url="https://hapijournal.com/2024/05/07/",
        read_date="2026-10-19",
        needs_expert_review=True,
        note=(
            "From 1 August 2024 the minimum invoice value requiring the buyer's national ID is EGP 25,000 instead "
            "of 50,000 (ETA head, quoted in the press). E-receipts have a separate figure and are out of scope."
        ),
    ),
)


def person_id_threshold(on: str) -> AmountThreshold | None:
    """The threshold in force on an ISO date (``YYYY-MM-DD...``), or ``None``."""
    day = (on or "")[:10]
    if len(day) != 10:
        return None
    for row in PERSON_ID_THRESHOLDS:
        if (not row.effective_from or row.effective_from <= day) and (not row.effective_to or day < row.effective_to):
            return row
    return None


# The only part of an EGS code ETA's partners document: it starts "EG-" (GS1
# Egypt, https://gs1eg.org/en/tools/eta-free-egs/). The rest of the layout is
# described inconsistently, so nothing beyond the prefix is checked.
EGS_CODE_PREFIX = "EG-"


@dataclass(frozen=True)
class ReviewedMapping:
    """A mapping of ours onto ETA codes, carried with its review status."""

    values: dict[str, str]
    needs_expert_review: bool
    note: str


# The platform's unit spellings onto ETA unit codes. Ours, not ETA's: the codes
# exist in UnitTypes.json, the pairing is a judgement. Note that ``KG`` in ETA's
# table is a keg; a kilogram is ``KGM``.
UNIT_MAP = ReviewedMapping(
    values={
        "m": "M",
        "lm": "M",
        "m2": "MTK",
        "m²": "MTK",
        "sqm": "MTK",
        "m3": "MTQ",
        "m³": "MTQ",
        "cbm": "MTQ",
        "kg": "KGM",
        "t": "TNE",
        "to": "TNE",
        "ton": "TNE",
        "l": "LTR",
        "ltr": "LTR",
        "h": "HUR",
        "hr": "HUR",
        "hrs": "HUR",
        "d": "DAY",
        "day": "DAY",
        "days": "DAY",
        "month": "MON",
        "mo": "MON",
        "pcs": "EA",
        "pc": "EA",
        "no": "EA",
        "nr": "EA",
        "ea": "EA",
        "each": "EA",
        "stk": "EA",
        "шт": "EA",
        # A lump sum has no ETA unit of its own; "activity unit" is the nearest.
        "ls": "C62",
        "lump sum": "C62",
        "item": "C62",
    },
    needs_expert_review=True,
    note="Platform unit spellings onto ETA unit codes; confirm with the taxpayer's tax advisor before a live filing.",
)

# The platform's EN 16931 VAT categories onto ETA T1 subtypes. Only the standard
# rate is mapped without a question: V009 is ETA's "General Item sales". The
# others depend on why the line is not standard rated, which the category alone
# does not say, so they are left for the operator to state on the line.
VAT_CATEGORY_SUBTYPES = ReviewedMapping(
    values={
        "S": "V009",
    },
    needs_expert_review=True,
    note=(
        "Only S (standard rate) maps to V009 by itself. Exempt, zero rated and out of scope lines need an explicit "
        "subtype (V001-V008, V010) on the line, because ETA distinguishes the reasons and the category does not."
    ),
)


def eta_unit_for(unit: str | None) -> str:
    """The ETA unit code for a platform unit, or ``""`` when there is none.

    A value that already is an ETA code passes through unchanged.
    """
    raw = (unit or "").strip()
    if not raw:
        return ""
    if raw in unit_types():
        return raw
    return UNIT_MAP.values.get(raw.lower(), "")


__all__ = [
    "EGS_CODE_PREFIX",
    "PERSON_ID_THRESHOLDS",
    "AmountThreshold",
    "person_id_threshold",
    "CODES_READ_DATE",
    "CODE_TABLE_SOURCES",
    "DOCUMENT_TYPES",
    "DOCUMENT_TYPE_VERSION",
    "DOC_CREDIT_NOTE",
    "DOC_DEBIT_NOTE",
    "DOC_EXPORT_CREDIT_NOTE",
    "DOC_EXPORT_DEBIT_NOTE",
    "DOC_EXPORT_INVOICE",
    "DOC_INVOICE",
    "EGP",
    "EXPORT_TYPES",
    "FIXED_AMOUNT_TYPES",
    "ITEM_TYPES",
    "NON_TAXABLE_FEES",
    "PARTY_BUSINESS",
    "PARTY_FOREIGNER",
    "PARTY_PERSON",
    "PARTY_TYPES",
    "REFERENCING_TYPES",
    "SDK_URL",
    "TAXABLE_FEES",
    "TAX_TABLE_FIXED",
    "TAX_TABLE_PERCENT",
    "TAX_VAT",
    "TAX_WITHHOLDING",
    "UNIT_MAP",
    "VAT_CATEGORY_SUBTYPES",
    "ReviewedMapping",
    "activity_codes",
    "eta_unit_for",
    "fixed_amount_subtypes",
    "subtype_belongs_to",
    "tax_subtype_descriptions",
    "tax_subtypes",
    "tax_types",
    "unit_types",
]
