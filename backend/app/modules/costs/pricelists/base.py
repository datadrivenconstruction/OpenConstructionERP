# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Shared shapes and value parsing for the regional price-list adapters.

Every adapter turns one publisher's file into the same two things: a
:class:`PriceListSource` that says whose list it is (region, edition, area,
licence, attribution) and a stream of :class:`PriceListRow`, one per priced
voce. The cost-database import builds ``CostItemCreate`` rows from those, so a
new region is a new reader and nothing downstream changes.

Numbers are the hard part. The lists are written by hand in spreadsheets and
exported by several generations of tools, so one file can carry "€ 1 826,34",
"13.63017", "8.6300000000000008" and "15.403.443". The first three are amounts
in three spellings; the last is an amount whose decimal separator was lost in
an export and cannot be recovered without guessing which dot was the decimal
one. :func:`parse_amount` reads the first three and reports the last as broken
instead of picking an answer, so a wrong number never enters a cost base
looking like a right one.

"1.250" is the other trap: 1250 in a list that writes "12,50", 1.25 in one
that writes "12.50", either on its own. A table learns its file's convention
from the cells only one reading fits (:class:`NumberConvention`) and reads it
that way; when the file does not settle it, the cell is broken too. An XML
list is typed by its schema, where the point is always the decimal separator.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any, ClassVar, Final

# ── Regions ──────────────────────────────────────────────────────────────────

#: The ministry region prefixes and the region each names. Trento and Bolzano
#: publish their own lists as autonomous provinces.
REGION_NAMES: Final[dict[str, str]] = {
    "ABR": "Abruzzo",
    "BAS": "Basilicata",
    "CAL": "Calabria",
    "CAM": "Campania",
    "EMR": "Emilia-Romagna",
    "FVG": "Friuli Venezia Giulia",
    "LAZ": "Lazio",
    "LIG": "Liguria",
    "LOM": "Lombardia",
    "MAR": "Marche",
    "MOL": "Molise",
    "PIE": "Piemonte",
    "PUG": "Puglia",
    "SAR": "Sardegna",
    "SIC": "Sicilia",
    "TOS": "Toscana",
    "UMB": "Umbria",
    "VDA": "Valle d'Aosta",
    "VEN": "Veneto",
    "TRE": "Provincia autonoma di Trento",
    "BOL": "Provincia autonoma di Bolzano",
}

#: Region prefix, edition year (two or four digits) and an optional edition
#: digit at the head of a code: ``TOS25_``, ``VEN26-``, ``LOM261.``,
#: ``CAM24_``, ``PUG2026/``.
_CODE_PREFIX_RE = re.compile(
    r"^(?P<region>" + "|".join(REGION_NAMES) + r")(?P<year>20\d{2}|\d{2})(?P<edition>\d)?[_./\-]"
)


def region_from_code(code: str) -> tuple[str, str] | None:
    """``(region_code, four digit year)`` read off a code's prefix, or ``None``."""
    match = _CODE_PREFIX_RE.match(code.strip())
    if not match:
        return None
    year = match.group("year")
    return match.group("region"), year if len(year) == 4 else f"20{year}"


# What each publisher's open-data catalogue record states about the licence,
# for the lists whose files say nothing themselves. Only records that were
# read are listed; a region absent here is reported as "not stated", never
# filled with a plausible guess. Source: the dati.gov.it catalogue records of
# the regional price lists, read on 2026-10-05.
CATALOGUE_LICENCES: Final[dict[str, str]] = {
    "TOS": "CC BY 4.0",
    "CAM": "CC BY 4.0",
    "PUG": "CC BY 4.0",
    "UMB": "CC BY 4.0",
    "PIE": "CC BY 4.0",
    "SIC": "CC BY 4.0",
}

# ── Rows ─────────────────────────────────────────────────────────────────────


@dataclass
class PriceListSource:
    """Whose list a file is, as far as the file and its layout say.

    ``detected_from`` records how the region was found, so the preview can ask
    the user to confirm a region inferred from a layout rather than read off
    the codes or the file header.
    """

    format_id: str
    profile: str = ""
    title: str = ""
    region_code: str | None = None
    edition: str | None = None
    area: str | None = None
    publisher: str | None = None
    licence: str | None = None
    licence_stated_in: str | None = None  # "file" | "catalogue" | None
    detected_from: str | None = None  # "file_header" | "code_prefix" | "layout" | "filename" | None

    @property
    def region_name(self) -> str | None:
        return REGION_NAMES.get(self.region_code or "")

    def resolve_licence(self) -> None:
        """Fill the licence from the catalogue table when the file states none."""
        if self.licence or not self.region_code:
            return
        catalogue = CATALOGUE_LICENCES.get(self.region_code)
        if catalogue:
            self.licence = catalogue
            self.licence_stated_in = "catalogue"

    def attribution(self) -> str:
        """The attribution line shown wherever rows from this list are offered."""
        publisher = self.publisher or (f"Regione {self.region_name}" if self.region_name else "")
        parts = [p for p in (publisher, self.title) if p]
        text = ", ".join(parts) if parts else "Regional price list"
        if self.edition and self.edition not in text:
            text += f", {self.edition}"
        if self.area and self.area not in text:
            text += f" ({self.area})"
        if self.licence:
            text += f", {self.licence}"
        return text

    def suggested_catalog_name(self) -> str:
        """``"Toscana 2025"``, with the area when the list is per area."""
        name = self.region_name or self.title or "Prezzario"
        if self.edition:
            name = f"{name} {self.edition}"
        if self.area:
            area = re.sub(r"^(?:provincia|citt[aà] metropolitana)\s+di\s+", "", self.area, flags=re.IGNORECASE)
            name = f"{name} - {area}"
        return name[:50]


@dataclass
class PriceListRow:
    """One priced voce, in the publisher's terms, before it becomes a cost item."""

    code: str
    description: str
    short_description: str = ""
    unit: str = ""
    source_unit: str = ""
    rate: Decimal | None = None
    chapters: list[tuple[str, str]] = field(default_factory=list)
    labour_share_pct: Decimal | None = None
    labour_amount: Decimal | None = None
    safety_share_pct: Decimal | None = None
    safety_amount: Decimal | None = None
    overhead_pct: Decimal | None = None
    profit_pct: Decimal | None = None
    components: list[dict[str, Any]] = field(default_factory=list)
    safety: bool = False
    flags: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)


# ── Numbers ──────────────────────────────────────────────────────────────────


class BrokenNumber(ValueError):
    """A cell that holds a number whose decimal separator cannot be told apart."""


_SPACE_CHARS = "    \t"
_STRIP_TOKENS_RE = re.compile(r"(?:€|eur(?:o)?\b|%)", re.IGNORECASE)

# One separator with exactly three digits after it and one to three before:
# "1.250" and "1,250" are a thousand and more as grouped integers and one and a
# quarter as decimals, and nothing in the cell says which.
_EITHER_WAY_RE = re.compile(r"^[1-9]\d{0,2}([.,])\d{3}$")


def _number_text(value: Any) -> str | None:
    """The digits and separators of a text cell, sign and currency removed, or ``None``."""
    if not isinstance(value, str):
        return None
    text = _STRIP_TOKENS_RE.sub("", value)
    for ch in _SPACE_CHARS:
        text = text.replace(ch, "")
    text = text.strip().lstrip("-")
    if not text or not re.fullmatch(r"[\d.,]+", text) or not any(c.isdigit() for c in text):
        return None
    return text


def decimal_separator_of(value: Any) -> str | None:
    """The decimal separator a text cell proves, or ``None`` when it proves none.

    "1.826,34" and "1,826.34" prove the later separator; "217,67", "13.63017"
    and "0.250" prove their only separator, since no grouping leaves other than
    three digits after it or starts a number with a nought. "1.250", "1250"
    and "15.403.443" prove nothing.
    """
    text = _number_text(value)
    if text is None or _EITHER_WAY_RE.match(text):
        return None
    dots, commas = text.count("."), text.count(",")
    if dots and commas:
        return "." if text.rfind(".") > text.rfind(",") else ","
    if dots == 1:
        return "."
    if commas == 1:
        return ","
    return None


@dataclass
class NumberConvention:
    """The decimal separator one file writes, learnt from the cells only one reading fits.

    A file that proves both (one cell "12,50", another "12.50") settles
    nothing, and its "1.250" stays broken.
    """

    #: Enough agreeing cells for a reader to stop looking.
    SETTLED_AFTER: ClassVar[int] = 200

    points: int = 0
    commas: int = 0

    def observe(self, value: Any) -> None:
        try:
            parse_amount(value)
        except BrokenNumber:
            # "1.234,5,6" proves nothing but that the cell is broken.
            return
        separator = decimal_separator_of(value)
        if separator == ".":
            self.points += 1
        elif separator == ",":
            self.commas += 1

    @property
    def decimal(self) -> str | None:
        if self.points and not self.commas:
            return "."
        if self.commas and not self.points:
            return ","
        return None

    @property
    def settled(self) -> bool:
        """Whether more cells could no longer change the answer in practice."""
        return self.decimal is not None and max(self.points, self.commas) >= self.SETTLED_AFTER


def parse_amount(value: Any, *, convention: NumberConvention | None = None) -> Decimal | None:
    """Read a price-list number, or ``None`` for an empty cell.

    Accepts a decimal comma or a decimal point, grouping by spaces or by the
    other separator ("1 826,34", "1.826,34", "1,826.34"), a currency or percent
    sign, and the float noise of a spreadsheet export ("8.6300000000000008",
    read as 8.63).

    Args:
        value: The cell.
        convention: The convention of the table the cell comes from. With
            one, "1.250" and "1,250" are read the way the file writes its
            numbers, and are broken when the file does not say. Without one
            the value is schema-typed (an XML attribute), where a point is the
            decimal separator.

    Raises:
        BrokenNumber: When the text has two or more dots and no comma
            ("15.403.443") or two or more commas and no dot. Either is a
            number whose decimal separator was lost, and the reading that
            looks right is a guess. Also for "1.250" in a table whose file
            does not settle its convention.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        raise BrokenNumber(str(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        if value != value:  # NaN
            return None
        return Decimal(repr(value))
    if isinstance(value, Decimal):
        return value
    text = _STRIP_TOKENS_RE.sub("", str(value))
    for ch in _SPACE_CHARS:
        text = text.replace(ch, "")
    text = text.strip()
    if not text or text in {"-", "--"}:
        return None
    negative = text.startswith("-")
    if negative:
        text = text[1:]
    if not re.fullmatch(r"[\d.,]+", text) or not any(c.isdigit() for c in text):
        raise BrokenNumber(str(value))
    either_way = _EITHER_WAY_RE.match(text)
    if either_way and convention is not None:
        decimal = convention.decimal
        if decimal is None:
            raise BrokenNumber(str(value))
        # The file's decimal separator is a decimal; the other one groups.
        text = text.replace(",", ".") if decimal == either_way.group(1) else text.replace(either_way.group(1), "")
    dots, commas = text.count("."), text.count(",")
    if dots and commas:
        decimal_sep = "." if text.rfind(".") > text.rfind(",") else ","
        group_sep = "," if decimal_sep == "." else "."
        whole, _, frac = text.rpartition(decimal_sep)
        groups = whole.split(group_sep)
        if decimal_sep in whole or any(len(g) != 3 for g in groups[1:]) or not groups[0]:
            raise BrokenNumber(str(value))
        normalised = "".join(groups) + "." + frac
    elif commas:
        if commas > 1:
            raise BrokenNumber(str(value))
        normalised = text.replace(",", ".")
    elif dots > 1:
        raise BrokenNumber(str(value))
    else:
        normalised = text
    try:
        number = Decimal(normalised)
    except InvalidOperation as exc:
        raise BrokenNumber(str(value)) from exc
    _, _, frac = normalised.partition(".")
    if len(frac) > 9:
        # A binary float written out in full by the exporter.
        number = Decimal(repr(float(normalised)))
    return -number if negative else number


def amount_or_flag(
    value: Any, label: str, flags: list[str], convention: NumberConvention | None = None
) -> Decimal | None:
    """:func:`parse_amount`, recording ``broken_number:<label>`` instead of raising."""
    try:
        return parse_amount(value, convention=convention)
    except BrokenNumber:
        flags.append(f"broken_number:{label}")
        return None


#: The line that closes the gap between an analysis and the list price.
BALANCE_NAME: Final = "Spese generali e utile d'impresa"


def settle_components(row: PriceListRow, components: list[dict[str, Any]], total: Decimal) -> None:
    """Hand an analysis to ``row`` as components that add up to its rate, or keep it as a record.

    The BOQ editor prices a line added from the cost database as the sum of
    its components, so components short of the list price would sell the voce
    for its bare analysis, and components over it for more than the list
    says. A list price carries general expenses and profit on top of the
    analysis: the gap becomes one balancing line under that name. An analysis
    that claims more than the price is kept under ``extra["analysis"]`` with
    an ``analysis_exceeds_price`` flag and does not become components.

    Args:
        row: The voce; its ``rate`` decides.
        components: The analysis lines, each with its ``cost``.
        total: Their costs added up exactly, before any float rounding.
    """
    if row.rate is None or not components:
        return
    balance = row.rate - total
    if balance < 0:
        row.flags.append("analysis_exceeds_price")
        row.extra["analysis"] = components
        return
    if balance > 0:
        components.append(
            {
                "code": "",
                "name": BALANCE_NAME,
                "unit": row.unit,
                "quantity": 1.0,
                "unit_rate": float(balance),
                "cost": float(balance),
                "type": "other",
            }
        )
    row.components = components


def decimal_str(value: Decimal | None) -> str | None:
    """A Decimal as the plain string metadata carries, ``None`` passed through."""
    if value is None:
        return None
    text = format(value.normalize(), "f")
    return "0" if text in {"-0", ""} else text


# ── Units ────────────────────────────────────────────────────────────────────

_UNIT_MAP: Final[dict[str, str]] = {
    "m": "m",
    "ml": "m",
    "m.l.": "m",
    "mt": "m",
    "m2": "m2",
    "mq": "m2",
    "m.q.": "m2",
    "m3": "m3",
    "mc": "m3",
    "m.c.": "m3",
    "dm3": "dm3",
    "cad": "pcs",
    "cad.": "pcs",
    "nr": "pcs",
    "n": "pcs",
    "n.": "pcs",
    "pz": "pcs",
    "num": "pcs",
    "numero": "pcs",
    "kg": "kg",
    "t": "t",
    "q": "q",
    "q.li": "q",
    "ql": "q",
    "l": "l",
    "lt": "l",
    "h": "hr",
    "ora": "hr",
    "ore": "hr",
    "gg": "day",
    "giorno": "day",
    "giorni": "day",
    "mese": "month",
    "corpo": "lsum",
    "a corpo": "lsum",
    "%": "%",
    "km": "km",
    "ha": "ha",
    "kw": "kW",
}
_SUPERSCRIPTS = str.maketrans({"²": "2", "³": "3"})
_UNIT_MAX = 20


def normalise_unit(raw: Any) -> str:
    """The platform's unit for a price-list unit, never empty.

    "m²" and "mq" become "m2", "cad" becomes "pcs", "ora" becomes "hr". A
    Lombardy unit carries its quantity ("1 m²", "100 kg"): a leading 1 is
    dropped and any other multiplier kept, since a rate per 100 kg is not a
    rate per kg. Anything not in the table is kept as written, compacted,
    in the characters a bill line's unit accepts: "1 m² * cm" (per square
    metre and centimetre of thickness) becomes "m2 x cm", since a unit the
    bill refuses would leave the voce importable and impossible to add.
    """
    text = unicodedata.normalize("NFKC", str(raw or "")).strip()
    text = re.sub(r"\s+", " ", text)
    if not text:
        return "pcs"
    multiplier = ""
    match = re.match(r"^(\d+)\s+(.+)$", text)
    if match:
        multiplier = "" if match.group(1) == "1" else f"{match.group(1)} "
        text = match.group(2)
    key = text.lower().translate(_SUPERSCRIPTS)
    # "€/m²" is a rate per square metre.
    key = re.sub(r"^(?:€|eur(?:o)?)\s*/\s*", "", key)
    unit = _UNIT_MAP.get(key)
    if unit is None:
        unit = re.sub(r"\s*[*×]\s*", " x ", key)
        unit = re.sub(r"\s*/\s*", "/", unit)
        unit = re.sub(r"[^\w .\-/%]", "", unit)
        unit = re.sub(r"\s+", " ", unit).strip(" ./-_")
    return (multiplier + unit)[:_UNIT_MAX].strip() or "pcs"


# ── Text ─────────────────────────────────────────────────────────────────────


def clean_text(value: Any) -> str:
    """Collapse whitespace and strip; ``None`` becomes ``""``."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value).replace(" ", " ")).strip()


def first_line(value: Any, limit: int = 160) -> str:
    """The first line (or sentence ending in a full stop) of a chapter text."""
    text = str(value or "").strip()
    head = text.splitlines()[0] if text else ""
    head = clean_text(head).rstrip(".")
    return head[:limit]


__all__ = [
    "CATALOGUE_LICENCES",
    "REGION_NAMES",
    "BALANCE_NAME",
    "BrokenNumber",
    "NumberConvention",
    "PriceListRow",
    "PriceListSource",
    "amount_or_flag",
    "decimal_separator_of",
    "clean_text",
    "decimal_str",
    "first_line",
    "normalise_unit",
    "parse_amount",
    "region_from_code",
    "settle_components",
]
