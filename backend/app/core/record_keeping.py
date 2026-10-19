# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""How long a country makes a business keep its records, and in which language.

Two national obligations every document store and invoice generator has to
respect, written down once per country as data with the article they come
from. Retention rules answer "until when must this record exist"; language
requirements answer "which language must this document carry, and which text
wins when two languages disagree".

Readers decide what to do with the answer. An archive keeps a record at least
until :func:`retain_until`; an invoice validator that knows which fields are
Arabic reads :func:`language_requirement` and checks them. This module does
not enforce anything by itself.

Standard library only; nothing here imports from ``app.modules``.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal

__all__ = [
    "LANGUAGE_REQUIREMENTS",
    "RETENTION_RULES",
    "LanguageRequirement",
    "RetentionRule",
    "language_requirement",
    "retain_until",
    "retention_rule",
    "validate_tables",
]

#: The day a retention period is counted from.
RETENTION_STARTS: tuple[str, ...] = ("end_of_tax_period", "acquisition", "document_date")


@dataclass(frozen=True)
class RetentionRule:
    """One minimum retention period for a class of records.

    Attributes:
        country_code: ISO 3166-1 alpha-2 code of the jurisdiction.
        record_class: A house key, ``general``, ``capital_assets`` or ``real_estate``.
        years: Minimum years to keep the records.
        plus_adjustment_period: True when ``years`` is added to the asset's
            adjustment period, which the caller supplies.
        starts_from: One of :data:`RETENTION_STARTS`.
        description: What the class covers, in English.
        legal_reference: The article the period comes from.
        source_url: Where it was read.
        read_date: ISO date the source was read.
        review_status: ``confirmed`` once read in the primary text.
        note: One sentence a person reads beside the figure.
    """

    country_code: str
    record_class: str
    years: int
    plus_adjustment_period: bool
    starts_from: Literal["end_of_tax_period", "acquisition", "document_date"]
    description: str
    legal_reference: str
    source_url: str
    read_date: str
    review_status: Literal["confirmed", "unconfirmed"]
    note: str = ""


@dataclass(frozen=True)
class LanguageRequirement:
    """The language a country requires on its tax documents and records.

    Attributes:
        country_code: ISO 3166-1 alpha-2 code of the jurisdiction.
        documents: House keys of the documents covered.
        required_language: ISO 639-1 code every covered document must carry.
        other_languages_allowed: Whether other languages may appear beside it.
        authoritative_language: The language whose text wins on a conflict.
        permitted_in_latin: What may stay in Latin script or Western digits
            and still meet the requirement, in English.
        legal_reference: The article the requirement comes from.
        source_url: Where it was read.
        read_date: ISO date the source was read.
        review_status: ``confirmed`` once read in the primary text.
    """

    country_code: str
    documents: tuple[str, ...]
    required_language: str
    other_languages_allowed: bool
    authoritative_language: str
    permitted_in_latin: tuple[str, ...]
    legal_reference: str
    source_url: str
    read_date: str
    review_status: Literal["confirmed", "unconfirmed"]


# ── Saudi Arabia ─────────────────────────────────────────────────────────

_SA_GUIDE = (
    "https://zatca.gov.sa/en/HelpCenter/guidelines/Documents/"
    "Guideline-for-Tax-Invoicing-and-Records-under-VAT-Provisions.pdf"
)
_SA_READ = "2026-10-19"

RETENTION_RULES: tuple[RetentionRule, ...] = (
    RetentionRule(
        country_code="SA",
        record_class="general",
        years=6,
        plus_adjustment_period=False,
        starts_from="end_of_tax_period",
        description="Tax invoices, accounting books, records and documents for VAT",
        legal_reference="VAT Implementing Regulations, Art. 66; ZATCA Tax Invoicing and Records guideline s. 8.3.3",
        source_url=_SA_GUIDE,
        read_date=_SA_READ,
        review_status="confirmed",
    ),
    RetentionRule(
        country_code="SA",
        record_class="capital_assets",
        years=5,
        plus_adjustment_period=True,
        starts_from="acquisition",
        description="Records of movable capital assets",
        legal_reference="VAT Implementing Regulations, Arts. 52 and 66; ZATCA Tax Invoicing and Records guideline s. 8.3.3",
        source_url=_SA_GUIDE,
        read_date=_SA_READ,
        review_status="confirmed",
        note=(
            "The adjustment period of Art. 52, plus five years, from acquisition; where the asset's useful life is "
            "under six years, the useful life plus five years. The caller supplies the period."
        ),
    ),
    RetentionRule(
        country_code="SA",
        record_class="real_estate",
        years=15,
        plus_adjustment_period=False,
        starts_from="document_date",
        description="Tax invoices, books, records and documents relating to real estate",
        legal_reference="VAT Implementing Regulations, Art. 66; ZATCA Tax Invoicing and Records guideline s. 8.3.3",
        source_url=_SA_GUIDE,
        read_date=_SA_READ,
        review_status="confirmed",
        note="Fifteen years in all cases. The guideline does not name the starting day; the document date is the earliest.",
    ),
)

LANGUAGE_REQUIREMENTS: tuple[LanguageRequirement, ...] = (
    LanguageRequirement(
        country_code="SA",
        documents=("tax_invoice", "simplified_tax_invoice", "credit_note", "debit_note", "records"),
        required_language="ar",
        other_languages_allowed=True,
        authoritative_language="ar",
        permitted_in_latin=(
            "Western digits 0-9 for amounts and dates (dates written day/month/year)",
            "Currency symbols and ISO 4217 currency codes",
            "Invoice numbers in digits or digits with letters",
            "Proper names of persons, places, branches and products",
        ),
        legal_reference="VAT Implementing Regulations, Art. 66(2) and 66(3); ZATCA Tax Invoicing and Records guideline s. 4.2.1",
        source_url=_SA_GUIDE,
        read_date=_SA_READ,
        review_status="confirmed",
    ),
)


# ── Reading ──────────────────────────────────────────────────────────────


def _country(value: str | None) -> str:
    return (value or "").strip().upper()


def retention_rule(
    country: str | None,
    record_class: str,
    rules: Sequence[RetentionRule] = RETENTION_RULES,
) -> RetentionRule | None:
    """The retention rule for one class of records, or ``None`` when none is on file."""
    wanted = _country(country)
    return next((r for r in rules if _country(r.country_code) == wanted and r.record_class == record_class), None)


def _add_years(start: date, years: int) -> date:
    try:
        return start.replace(year=start.year + years)
    except ValueError:  # 29 February into a common year
        return start.replace(year=start.year + years, day=28)


def retain_until(rule: RetentionRule, start: date, *, adjustment_period_years: int | None = None) -> date | None:
    """The earliest day a record may be destroyed under ``rule``.

    Args:
        rule: The retention rule.
        start: The day named by ``rule.starts_from`` (the end of the tax
            period, the acquisition or the document date).
        adjustment_period_years: The asset's adjustment period, required when
            ``rule.plus_adjustment_period`` is set.

    Returns:
        The date, or ``None`` when the rule needs an adjustment period that
        was not given: a guessed period would shorten the retention silently.
    """
    years = rule.years
    if rule.plus_adjustment_period:
        if adjustment_period_years is None:
            return None
        years += adjustment_period_years
    return _add_years(start, years)


def language_requirement(
    country: str | None,
    requirements: Sequence[LanguageRequirement] = LANGUAGE_REQUIREMENTS,
) -> LanguageRequirement | None:
    """The country's document language requirement, or ``None`` when none is on file."""
    wanted = _country(country)
    return next((r for r in requirements if _country(r.country_code) == wanted), None)


def validate_tables(
    rules: Sequence[RetentionRule],
    requirements: Sequence[LanguageRequirement],
) -> list[str]:
    """Describe everything that makes the tables unsafe to read; empty for sound ones."""
    problems: list[str] = []
    seen: set[tuple[str, str]] = set()
    for rule in rules:
        where = f"{_country(rule.country_code)}/{rule.record_class}"
        key = (_country(rule.country_code), rule.record_class)
        if key in seen:
            problems.append(f"{where}: more than one rule for the class")
        seen.add(key)
        if len(key[0]) != 2:
            problems.append(f"{where}: country_code is not ISO 3166-1 alpha-2")
        if rule.years <= 0:
            problems.append(f"{where}: years must be positive")
        if rule.starts_from not in RETENTION_STARTS:
            problems.append(f"{where}: starts_from {rule.starts_from!r} is not one of {RETENTION_STARTS}")
        problems.extend(_source_problems(where, rule.legal_reference, rule.source_url, rule.read_date))
    for requirement in requirements:
        where = f"{_country(requirement.country_code)}/language"
        if not requirement.documents:
            problems.append(f"{where}: no documents named")
        if len(requirement.required_language) != 2 or len(requirement.authoritative_language) != 2:
            problems.append(f"{where}: languages must be ISO 639-1 codes")
        problems.extend(
            _source_problems(where, requirement.legal_reference, requirement.source_url, requirement.read_date)
        )
    return problems


def _source_problems(where: str, reference: str, url: str, read_date: str) -> list[str]:
    problems: list[str] = []
    if not reference.strip():
        problems.append(f"{where}: legal_reference is empty")
    if not url.startswith("https://"):
        problems.append(f"{where}: source_url must be an https address")
    try:
        date.fromisoformat(read_date)
    except ValueError:
        problems.append(f"{where}: read_date {read_date!r} is not an ISO date")
    return problems
