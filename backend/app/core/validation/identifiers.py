# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""National identifiers, as data rows that say where each rule came from.

One validator answers for every country: :func:`validate_identifier` takes a
country, a kind and a value, and judges the value by the row filed under that
country and kind. A country is added by adding rows, never code. The kinds are
the ones a construction company meets on its counterparties and staff:

* ``tax_registration``: the number the tax authority registers a business
  under (a company's tax ID, not its VAT number where the two differ).
* ``national_id``: a person's national identity number.
* ``company_register``: the commercial or trade register number.

Every row carries its source, the source's URL, the date the rule took effect,
a confidence and a ``needs_expert_review`` flag. A rule that was not read in a
primary text is flagged, and stays as permissive as the sources agree on: the
point is to catch a mistyped number at the form, not to authenticate it.

A row can describe a number's inner structure as data (:class:`DateCodedId`):
where a birth date sits, which century a leading digit names, which region
codes exist and which digit carries the holder's sex. That is how a national
ID is checked without a function per country. A check digit is verified only
when a row names an algorithm, and no row does yet.

Digits typed on an Arabic or Persian keyboard are digits. ``٢٨٥`` and ``۲۸۵``
are read as ``285``, because an Egyptian clerk types the former and nothing
else in the value changes.

The subcontractor tax-ID check (``app.modules.subcontractors.tax_id``) reads
the ``tax_registration`` row of a country its own table does not have, so a
tax number filed here has exactly one home.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

__all__ = [
    "IDENTIFIER_KINDS",
    "IDENTIFIER_RULES",
    "DateCodedId",
    "IdentifierResult",
    "IdentifierRule",
    "normalise_digits",
    "rule_for",
    "validate_identifier",
]

IDENTIFIER_KINDS: frozenset[str] = frozenset({"tax_registration", "national_id", "company_register"})

#: Arabic-Indic (U+0660..) and extended Arabic-Indic (U+06F0..) digits to ASCII.
_DIGIT_MAP: dict[int, int] = {
    **{0x0660 + n: ord("0") + n for n in range(10)},
    **{0x06F0 + n: ord("0") + n for n in range(10)},
}

#: What a person types between groups and a register prints: spaces (including
#: no-break and narrow no-break), dashes, dots, slashes.
_SEPARATORS = re.compile(r"[\s  \-‐‑./]")


def normalise_digits(value: str) -> str:
    """``value`` with Arabic-Indic and Persian digits written as ASCII digits."""
    return value.translate(_DIGIT_MAP)


@dataclass(frozen=True)
class DateCodedId:
    """The structure of an identifier that encodes its holder's birth date.

    Positions are zero-based slices into the normalised value.

    Attributes:
        century_index: Position of the digit naming the century.
        centuries: That digit's value -> the first year of the century.
        date_slice: ``(start, end)`` of the ``YYMMDD`` birth date.
        region_slice: ``(start, end)`` of the region code, or ``None``.
        region_codes: The region codes that exist, code -> name.
        sex_index: Position of the digit whose parity gives the sex (odd male).
    """

    century_index: int
    centuries: dict[str, int]
    date_slice: tuple[int, int]
    region_slice: tuple[int, int] | None = None
    region_codes: dict[str, str] = field(default_factory=dict)
    sex_index: int | None = None


@dataclass(frozen=True)
class IdentifierRule:
    """One country's rule for one kind of identifier.

    Attributes:
        country: ISO 3166-1 alpha-2.
        kind: One of :data:`IDENTIFIER_KINDS`.
        label: The standard's name as printed, e.g. ``"EG RIN"``.
        pattern: Full-match regex on the normalised value (separators gone,
            digits in ASCII).
        source: The text the rule was read from.
        source_url: Where that text is.
        effective_from: The date the rule is known to apply from. When no
            source gives the enacting date, the date the source was read,
            so the row never claims an age nobody checked.
        confidence: ``H`` read in a primary text, ``M`` consistent secondary
            sources, ``L`` thin or conflicting.
        needs_expert_review: The rule has not been confirmed by a primary text
            or a local expert; it ships as data, not as a settled fact.
        structure: Inner structure checked after the pattern, if any.
        note: What the rule deliberately does not check, and why.
    """

    country: str
    kind: str
    label: str
    pattern: re.Pattern[str]
    source: str
    source_url: str
    effective_from: date
    confidence: str
    needs_expert_review: bool
    structure: DateCodedId | None = None
    note: str = ""


@dataclass(frozen=True)
class IdentifierResult:
    """What :func:`validate_identifier` found.

    Attributes:
        passed: ``True`` when the value fits the row, or when there is no row
            (an unknown country is not judged, it is not refused).
        normalised: The value with separators removed and digits in ASCII.
        reason: Why it failed: ``empty``, ``length``, ``format``, ``century``,
            ``birth_date`` or ``region_code``; ``None`` when it passed.
        rule: The row that judged it, ``None`` when nothing did.
        details: What the structure revealed (birth date, region, sex).
        checksum_verified: Whether a check digit was verified. Always
            ``False`` until a row names an algorithm.
    """

    passed: bool
    normalised: str
    reason: str | None = None
    rule: IdentifierRule | None = None
    details: dict[str, str] = field(default_factory=dict)
    checksum_verified: bool = False

    @property
    def needs_expert_review(self) -> bool:
        """Whether the rule that judged the value still awaits confirmation."""
        return bool(self.rule and self.rule.needs_expert_review)


# -- Egypt ---------------------------------------------------------------------

#: Governorate codes printed in digits 8-9 of the Egyptian national ID, and 88
#: for a holder born outside the republic. Secondary source; no civil-status
#: list was reachable.
_EG_GOVERNORATES: dict[str, str] = {
    "01": "Cairo",
    "02": "Alexandria",
    "03": "Port Said",
    "04": "Suez",
    "11": "Damietta",
    "12": "Dakahlia",
    "13": "Sharqia",
    "14": "Qalyubia",
    "15": "Kafr El Sheikh",
    "16": "Gharbia",
    "17": "Monufia",
    "18": "Beheira",
    "19": "Ismailia",
    "21": "Giza",
    "22": "Beni Suef",
    "23": "Fayoum",
    "24": "Minya",
    "25": "Asyut",
    "26": "Sohag",
    "27": "Qena",
    "28": "Aswan",
    "29": "Luxor",
    "31": "Red Sea",
    "32": "New Valley",
    "33": "Matruh",
    "34": "North Sinai",
    "35": "South Sinai",
    "88": "Born abroad",
}

#: No source read for these rows gives the date the format took effect, so the
#: rows date themselves from the day the sources were read.
_EG_READ_ON = date(2026, 10, 19)

_EG_ROWS: tuple[IdentifierRule, ...] = (
    IdentifierRule(
        country="EG",
        kind="tax_registration",
        label="EG RIN",
        pattern=re.compile(r"^\d{9}$"),
        source=(
            "Egyptian Tax Authority e-invoicing SDK, invoice v1.0 (issuer/receiver id is the "
            "registration number; the SDK states no length). Nine digits, printed 123-456-789, "
            "per consistent secondary sources."
        ),
        source_url="https://sdk.invoicing.eta.gov.eg/documents/invoice-v1-0/",
        effective_from=_EG_READ_ON,
        confidence="M",
        needs_expert_review=True,
        note="No check digit is verified; none is published.",
    ),
    IdentifierRule(
        country="EG",
        kind="national_id",
        label="EG National ID",
        pattern=re.compile(r"^\d{14}$"),
        source=(
            "Structure as documented for the Egyptian national identity card: century digit, "
            "YYMMDD birth date, governorate code, serial whose last digit gives the sex, check digit."
        ),
        source_url="https://en.wikipedia.org/wiki/Egyptian_National_Identity_Card",
        effective_from=_EG_READ_ON,
        confidence="M",
        needs_expert_review=True,
        structure=DateCodedId(
            century_index=0,
            centuries={"2": 1900, "3": 2000},
            date_slice=(1, 7),
            region_slice=(7, 9),
            region_codes=_EG_GOVERNORATES,
            sex_index=12,
        ),
        note="The final check digit is not verified: its algorithm is not published.",
    ),
    IdentifierRule(
        country="EG",
        kind="company_register",
        label="EG Commercial Register",
        pattern=re.compile(r"^\d{1,10}$"),
        source=(
            "Law 34/1976 on the Commercial Register keeps a register per office and gives the "
            "number no national format; accepted as 1 to 10 digits."
        ),
        source_url="https://alp.unescwa.org/legislations/law-34-1976-commercial-registry",
        effective_from=_EG_READ_ON,
        confidence="L",
        needs_expert_review=True,
        note="Numbers are issued per registry office; the office is not part of the check.",
    ),
)

#: Every row, keyed by ``(country, kind)``.
IDENTIFIER_RULES: dict[tuple[str, str], IdentifierRule] = {(row.country, row.kind): row for row in (*_EG_ROWS,)}


def rule_for(country: str | None, kind: str) -> IdentifierRule | None:
    """The row for ``country`` and ``kind``, or ``None`` when there is none."""
    return IDENTIFIER_RULES.get(((country or "").strip().upper(), kind))


def _check_structure(value: str, structure: DateCodedId) -> tuple[str | None, dict[str, str]]:
    """``(reason, details)`` for a value that already matched its pattern."""
    century = structure.centuries.get(value[structure.century_index])
    if century is None:
        return "century", {}
    start, end = structure.date_slice
    yy, mm, dd = int(value[start : start + 2]), int(value[start + 2 : start + 4]), int(value[start + 4 : end])
    try:
        born = date(century + yy, mm, dd)
    except ValueError:
        return "birth_date", {}
    if born > date.today():
        return "birth_date", {}
    details = {"birth_date": born.isoformat()}
    if structure.region_slice is not None:
        region = value[structure.region_slice[0] : structure.region_slice[1]]
        if region not in structure.region_codes:
            return "region_code", details
        details["region_code"] = region
        details["region"] = structure.region_codes[region]
    if structure.sex_index is not None:
        details["sex"] = "male" if int(value[structure.sex_index]) % 2 else "female"
    return None, details


def validate_identifier(country: str | None, kind: str, value: str | None) -> IdentifierResult:
    """Judge ``value`` by the row filed for ``country`` and ``kind``.

    Args:
        country: ISO 3166-1 alpha-2, any case.
        kind: One of :data:`IDENTIFIER_KINDS`.
        value: As typed: separators and Arabic-Indic digits are fine.

    Returns:
        An :class:`IdentifierResult`. With no row the value passes unjudged
        (``rule is None``), the way the tax-ID check treats an unknown country.
    """
    normalised = _SEPARATORS.sub("", normalise_digits(value or "")).upper()
    rule = rule_for(country, kind)
    if not normalised:
        return IdentifierResult(passed=False, normalised="", reason="empty", rule=rule)
    if rule is None:
        return IdentifierResult(passed=True, normalised=normalised)
    if not rule.pattern.fullmatch(normalised):
        reason = "length" if rule.structure is not None else "format"
        return IdentifierResult(passed=False, normalised=normalised, reason=reason, rule=rule)
    if rule.structure is not None:
        reason, details = _check_structure(normalised, rule.structure)
        return IdentifierResult(passed=reason is None, normalised=normalised, reason=reason, rule=rule, details=details)
    return IdentifierResult(passed=True, normalised=normalised, rule=rule)
